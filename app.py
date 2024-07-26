import os
from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit
from werkzeug.utils import secure_filename
import datetime
import time
import threading
import requests
from requests.auth import HTTPDigestAuth
import xml.etree.ElementTree as ET
from tqdm import tqdm


app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app)

channel_dict = {
    "程序1": 101,
    "策划1": 201,
    "程序2": 301,
    "沙发区机房": 401,
    "程序3": 501,
    "美术2": 601,
    "美术1": 701,
    "策划2": 801,
    "市场行政": 901,
    "正门": 1001,
    "吧台": 1101,
    # 添加更多通道
}

def get_playback_uris(username, password, base_url, track_id, start_time, end_time):
    url = f"{base_url}/ISAPI/ContentMgmt/search"
    payload = f"""
    <CMSearchDescription>
        <searchID>88C2CD4D-D3FA-4AD4-BD80-555C18205DCC</searchID>
        <trackList>
            <trackID>{track_id}</trackID>
        </trackList>
        <timeSpanList>
            <timeSpan>
                <startTime>{start_time}</startTime>
                <endTime>{end_time}</endTime>
            </timeSpan>
        </timeSpanList>
        <maxResults>40</maxResults>
        <searchResultPosition>0</searchResultPosition>
    </CMSearchDescription>
    """
    headers = {
        'Content-Type': 'application/xml'
    }

    response = requests.post(url, headers=headers, auth=HTTPDigestAuth(username, password), data=payload)
    if response.status_code == 200:
        root = ET.fromstring(response.content)
        namespaces = {'ns': 'http://www.hikvision.com/ver20/XMLSchema'}
        playback_uris = [
            {
                "uri": uri.text,
                "track_id": track_id,
                "start_time": ts.find("ns:startTime", namespaces).text,
                "end_time": ts.find("ns:endTime", namespaces).text
            }
            for uri, ts in zip(root.findall('.//ns:playbackURI', namespaces), root.findall('.//ns:timeSpan', namespaces))
        ]
        return playback_uris
    else:
        print(f"查询失败，状态码: {response.status_code}")
        return []

def download_video(username, password, base_url, playback_uri, track_id, folder):
    url = f"{base_url}/ISAPI/ContentMgmt/download"
    payload = f"""
    <downloadRequest xmlns="http://www.isapi.org/ver20/XMLSchema" version="2.0">
        <playbackURI>{playback_uri}</playbackURI>
        <mediaID>{track_id}</mediaID>
        <downType>byFileName</downType>
        <encodeType>H.264-BP</encodeType>
    </downloadRequest>
    """
    headers = {
        'Content-Type': 'application/xml'
    }

    response = requests.post(url, headers=headers, auth=HTTPDigestAuth(username, password), data=payload, stream=True)

    if response.status_code == 200:
        start_time = playback_uri.split("starttime=")[1].split("&")[0]
        end_time = playback_uri.split("endtime=")[1].split("&")[0]
        start_time = datetime.datetime.strptime(start_time, "%Y%m%dT%H%M%SZ")
        end_time = datetime.datetime.strptime(end_time, "%Y%m%dT%H%M%SZ")
        filename = os.path.join(folder, f"{start_time.strftime('%Y%m%d_%H%M%S')}-{end_time.strftime('%Y%m%d_%H%M%S')}.mp4")
        total_size = int(response.headers.get('content-length', 0))
        with open(filename, 'wb') as file, tqdm(
                desc=f"正在下载文件: {filename}",
                total=total_size,
                unit='B',
                unit_scale=True,
                unit_divisor=1024,
        ) as bar:
            for data in response.iter_content(chunk_size=1024):
                size = file.write(data)
                bar.update(size)
        print(f"文件下载完成: {filename}")
        socketio.emit('update', {'message': f'文件下载完成: {filename}'})
    else:
        print(f"下载失败，状态码: {response.status_code}")
        print(response.text)
        socketio.emit('update', {'message': f'下载失败，状态码: {response.status_code}'})

def download_videos_for_date(username, password, base_url, channel_name, date_str):
    track_id = channel_dict.get(channel_name)
    if not track_id:
        print(f"未找到通道名称: {channel_name}")
        return

    start_time = f"{date_str}T00:00:00Z"
    end_time = f"{date_str}T23:59:59Z"

    print(f"正在解析{channel_name}的录像文件...")

    playback_uris = get_playback_uris(username, password, base_url, track_id, start_time, end_time)
    for item in playback_uris:
        folder = os.path.join('download_files', channel_name, date_str)
        os.makedirs(folder, exist_ok=True)
        download_video(username, password, base_url, item['uri'], item['track_id'], folder)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/progress')
def progress():
    return render_template('progress.html')

@app.route('/download', methods=['POST'])
def download():
    channels = request.form.getlist('channels[]')
    dates = request.form['dates'].split(',')
    username = 'admin'
    password = 'q1234567'
    base_url = "http://10.0.26.2"

    print(f"Received channels: {channels}")
    print(f"Received dates: {dates}")

    def run_download():
        with open('download_logs.txt', 'a') as log_file:
            for channel_name in channels:
                for date in dates:
                    log_file.write(f"正在下载通道: {channel_name} 日期: {date}\n")
                    print(f"正在下载通道: {channel_name} 日期: {date}")
                    download_videos_for_date(username, password, base_url, channel_name, date)
                    log_file.write(f"完成下载通道: {channel_name} 日期: {date}\n")
                    print(f"完成下载通道: {channel_name} 日期: {date}")

    thread = threading.Thread(target=run_download)
    thread.start()
    return jsonify(success=True)

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=80)
