import os
import tempfile
import requests
import random
import json
from flask import Flask, request, render_template, redirect, url_for, flash, session, jsonify

app = Flask(__name__)

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
        with open(history_file, 'w', encoding='utf-8') as f:  # 确保用 UTF-8 编码写入文件
            json.dump([], f)

    # 读取现有的历史记录，指定 UTF-8 编码
    with open(history_file, 'r', encoding='utf-8') as f:
        history = json.load(f)

    # 添加新链接和描述信息
    history.append({'link': link, 'description': description})

    # 将更新后的历史记录写回文件，确保写入时也使用 UTF-8 编码
    with open(history_file, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=4)


# 文件上传处理
def upload_file(file_path, mime_type, description):
    url = get_url()
    if url is None:
        return {'status': 'error', 'message': '无法获取上传地址'}

    with open(file_path, 'rb') as file:
        headers = {
            'Content-Type': mime_type,
            'User-Agent': get_random_user_agent()
        }
        response = requests.put(url, data=file, headers=headers)

    if response.status_code != 200:
        return {'status': 'error', 'message': '上传失败，错误：' + response.text}

    share_link = url + '?response-content-type=' + requests.utils.quote(mime_type)
    save_link_to_file(share_link, description)  # 保存链接和描述
    return {'status': 'success', 'share_link': share_link}

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
    
    if request.method == 'POST':
        # 检查请求中是否包含文件
        if 'files' not in request.files:
            return jsonify({'status': 'error', 'message': '未选择文件'})

        # 获取上传的多个文件
        files = request.files.getlist('files')  # 使用 `getlist` 以获取多个文件

        if len(files) == 0:
            return jsonify({'status': 'error', 'message': '文件列表为空'})

        upload_results = []  # 存储每个文件的上传结果
        description = request.form.get('description', '')  # 获取描述信息，可能为空
        for file in files:
            temp_dir = tempfile.gettempdir()
            file_path = os.path.join(temp_dir, file.filename)
            file.save(file_path)
            mime_type = file.content_type

            # 使用文件名作为默认描述
            file_description = description or file.filename

            result = upload_file(file_path, mime_type, file_description)
            os.remove(file_path)

            # 为每个文件单独生成结果
            upload_results.append({'filename': file.filename, **result})

        return jsonify({'status': 'success', 'results': upload_results})

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
