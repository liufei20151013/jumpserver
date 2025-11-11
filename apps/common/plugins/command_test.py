# -*- coding: utf-8 -*-

import requests
import json
import threading
import time


def get_token(jms_url, username, password):
    url = jms_url + '/api/v1/authentication/auth/'
    query_args = {
        "username": username,
        "password": password
    }
    response = requests.post(url, data=query_args)
    return json.loads(response.text)['token']


def get_commands(jms_url, token):
    url = jms_url + '/api/v1/terminal/commands/?command_storage_id=6898a18b-cb76-4cea-b284-c3865576f5cf&order=-timestamp&date_to=2025-11-10T07%3A41%3A45.795Z&date_from=2024-11-10T07%3A41%3A45.795Z&asset=10.1.12.226-224&offset=0&limit=1000&display=1&draw=1'
    headers = {
        "Authorization": 'Bearer ' + token,
        'X-JMS-ORG': '00000000-0000-0000-0000-000000000002'
    }
    response = requests.get(url, headers=headers)
    print(f"请求状态码: {response.status_code}, 线程ID: {threading.current_thread().ident}")
    # print(f"请求状态码: {response.text}, 线程ID: {threading.current_thread().ident}")
    print(f"结果数: {len(json.loads(response.text)['results'])}, 线程ID: {threading.current_thread().ident}")



def main():
    jms_url = 'http://ip'  #堡垒机 IP
    username = 'admin'
    password = '*****'
    token = get_token(jms_url, username, password)

    # 并发调用600次，每次间隔0.1秒
    for i in range(1600):
        # 创建线程
        t = threading.Thread(target=get_commands, args=(jms_url, token))
        t.start()
        # 间隔1秒再创建下一个线程
        time.sleep(0.5)

    # 等待所有线程完成（可选）
    main_thread = threading.current_thread()
    for thread in threading.enumerate():
        if thread is not main_thread:
            thread.join()


if __name__ == '__main__':
    main()
