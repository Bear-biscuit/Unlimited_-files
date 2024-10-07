import os
import requests
import random
import json
from tqdm import tqdm
import logging
import urllib.parse
from werkzeug.utils import secure_filename
from flask import Flask, request, render_template, redirect, url_for, flash, session, jsonify

app = Flask(__name__)

# 创建一个自定义日志过滤器
class RequestFilter(logging.Filter):
    def filter(self, record):
        
        # 过滤掉包含 'POST /upload_chunk' 的日志
        if 'POST /upload_chunk' in record.getMessage():
            return False 
        return True  

# 获取Flask默认的日志记录器
log = logging.getLogger('werkzeug')

# 添加过滤器到日志记录器
log.addFilter(RequestFilter())

app.secret_key = 'session_bMabnsuaa'

ITEMS_PER_PAGE = 10  # 每页显示的条目数

# 硬编码用户名和密码
USERNAME = "admin"
PASSWORD = "password"

# 获取上传地址的函数
def get_url():
    response = requests.get('https://video-oss.vercel.app/link')
    if response.status_code != 200:
        return None
    return response.text.strip()

# 生成随机 User-Agent
def get_random_user_agent():
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.121 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Safari/605.1.15',
        'Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1',
        'Mozilla/5.0 (Linux; Android 10; SM-G975F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.121 Mobile Safari/537.36',
        'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:80.0) Gecko/20100101 Firefox/80.0'
    ]
    return random.choice(user_agents)

# 保存链接到 JSON 文件
def save_link_to_file(link, description):
    history_file = 'history.json'

    # 如果文件不存在，创建一个空的 JSON 列表
    if not os.path.exists(history_file):
        with open(history_file, 'w', encoding='utf-8') as f:
            json.dump([], f)

    # 读取现有的历史记录
    with open(history_file, 'r', encoding='utf-8') as f:
        history = json.load(f)

    # 添加新链接和描述信息
    history.append({'link': link, 'description': description})

    # 将更新后的历史记录写回文件
    with open(history_file, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=4)

def sanitize_filename(filename):
    # 分离文件名和扩展名
    name, ext = os.path.splitext(filename)
    # 使用 secure_filename 处理文件名部分，但保留扩展名
    safe_name = secure_filename(name)
    return f"{safe_name}{ext}"

# 分块上传处理
@app.route('/upload_chunk', methods=['POST'])
def upload_chunk():
    if not session.get('logged_in'):
        return jsonify({'status': 'error', 'message': '未登录'})

    if 'file' not in request.files:
        return jsonify({'status': 'error', 'message': '未找到文件'})

    file = request.files['file']
    filename = request.form.get('filename')
    current_chunk = int(request.form.get('current_chunk'))
    total_chunks = int(request.form.get('total_chunks'))
    description = request.form.get('description', filename)
    # 使用安全的文件名
    safe_filename = sanitize_filename(filename)

    # 定义临时目录路径
    temp_dir = os.path.join('temp_chunks', safe_filename)
    chunk_filename = os.path.join(temp_dir, f'chunk_{current_chunk}')

    # 创建临时目录
    try:
        if not os.path.exists(temp_dir):
            os.makedirs(temp_dir)
    except Exception as e:
        return jsonify({'status': 'error', 'message': '无法创建临时目录，权限错误'})

    # 保存文件块
    try:
        file.save(chunk_filename)
    except Exception as e:
        return jsonify({'status': 'error', 'message': '无法保存文件块，权限错误'})

    # 如果所有块都上传完成，合并文件
    if current_chunk == total_chunks - 1:
        final_file_path = os.path.join('temp_chunks', safe_filename, safe_filename)  # 指定文件名
        try:
            with open(final_file_path, 'wb') as final_file:
                for i in range(total_chunks):
                    chunk_file = os.path.join(temp_dir, f'chunk_{i}')

                    # 确保每个文件块都被正确读取和合并
                    with open(chunk_file, 'rb') as chunk:
                        final_file.write(chunk.read())
                    # 合并后删除块文件
                    try:
                        os.remove(chunk_file)
                    except Exception as e:
                        print(f"Error deleting chunk file: {chunk_file}, error: {e}") 
        except Exception as e:
            return jsonify({'status': 'error', 'message': f'无法合并文件，错误：{e}'})

        # 上传文件到 OSS
        mime_type = request.form.get('mime_type', 'application/octet-stream')
        result = upload_file(final_file_path, mime_type, description,filename)

        # 删除本地临时文件
        try:
            os.remove(final_file_path)
        except Exception as e:
            print(f"Error deleting merged file: {final_file_path}, error: {e}")
        # 删除临时目录
        try:
            os.rmdir(temp_dir)
        except Exception as e:
            print(f"Error deleting temp directory: {temp_dir}, error: {e}")

        if result['status'] == 'success':
            return jsonify({'status': 'success', 'share_link': result['share_link']})
        else:
            return jsonify({'status': 'error', 'message': result['message']})
    
    return jsonify({'status': 'chunk_uploaded', 'message': f'第 {current_chunk + 1}/{total_chunks} 块上传成功'})



# 文件上传到OSS的函数
def upload_file(file_path, mime_type, description,filename):
    url = get_url()
    if url is None:
        return {'status': 'error', 'message': '无法获取上传地址'}
    filename = urllib.parse.quote(filename)
    try:
        # 获取文件大小
        file_size = os.path.getsize(file_path)
        headers = {
            'Content-Type': 'image/jpeg',
            'User-Agent': get_random_user_agent(),
            'Content-Disposition': f'attachment; filename*=UTF-8\'\'{filename}'
        }

        # 打开文件，准备以二进制流形式上传
        with open(file_path, 'rb') as file:
            # 进度条
            with tqdm(total=file_size, unit='B', unit_scale=True, desc="上传进度") as progress_bar:
                # 自定义生成器，逐块读取文件
                def file_reader():
                    chunk_size = 1024 * 1024  # 每次读取1MB
                    while True:
                        chunk = file.read(chunk_size)
                        if not chunk:
                            break
                        yield chunk
                        progress_bar.update(len(chunk))  # 更新进度条

                # 上传文件，使用分块上传
                response = requests.put(url, data=file_reader(), headers=headers)

        # 检查上传请求的响应状态
        if response.status_code != 200:
            # 返回更多详细的错误提示信息
            return {
                'status': 'error', 
                'message': f'上传失败，状态码：{response.status_code}，服务器返回信息：{response.text}'
            }

        # 构建文件分享链接
        share_link = f"{url}?response-content-type={requests.utils.quote(mime_type)}"
        save_link_to_file(share_link, description)  # 保存链接和描述
        return {'status': 'success', 'share_link': share_link}

    except requests.exceptions.RequestException as e:
        # 捕获网络错误等异常，并返回详细信息
        return {
            'status': 'error', 
            'message': f'请求异常：{str(e)}'
        }



# 登录页面
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        # 检查用户名和密码是否匹配
        if username == USERNAME and password == PASSWORD:
            session['logged_in'] = True
            flash('登录成功！')
            return redirect(url_for('upload'))
        else:
            flash('用户名或密码错误，请重试。')

    return render_template('login.html')

# 登出功能
@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    flash('您已登出。')
    return redirect(url_for('login'))

@app.route('/', methods=['GET', 'POST'])
def upload():
    if not session.get('logged_in'):
        return redirect(url_for('login'))  # 如果未登录，重定向到登录页面

    return render_template('upload.html')



@app.route('/history')
def history():
    if not session.get('logged_in'):
        return redirect(url_for('login'))  # 如果未登录，重定向到登录页面
    history_file = 'history.json'
    history = []

    if os.path.exists(history_file):
        with open(history_file, 'r', encoding='utf-8') as f:  # 确保以UTF-8编码读取文件
            history = json.load(f)

    # 获取当前页码，默认页码为1
    page = int(request.args.get('page', 1))
    total_pages = (len(history) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE

    start_idx = (page - 1) * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    current_page_history = history[start_idx:end_idx]

    return render_template('history.html', history=current_page_history, page=page, total_pages=total_pages)

@app.route('/delete', methods=['POST'])
def delete_record():
    if not session.get('logged_in'):
        return redirect(url_for('login'))  # 如果未登录，重定向到登录页面
    link_to_delete = request.form.get('link')
    history_file = 'history.json'

    if not os.path.exists(history_file):
        return jsonify({'status': 'error', 'message': '历史记录文件不存在'})

    with open(history_file, 'r', encoding='utf-8') as f:
        history = json.load(f)

    # 删除指定链接的记录
    history = [entry for entry in history if entry['link'] != link_to_delete]

    with open(history_file, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=4)

    return jsonify({'status': 'success', 'message': '记录已删除'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
