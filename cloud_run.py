import os
import datetime
import requests
import smtplib
import re
from email.mime.text import MIMEText
from email.header import Header
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# ================= 配置区 (GitHub Secrets 会覆盖这里) =================
# 在本地测试时，可以直接填入；上传到 GitHub 前请清空或保留空字符串
SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.qq.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 465))
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "")
SENDER_PASSWORD = os.environ.get("SENDER_PASSWORD", "")
RECEIVER_EMAIL = os.environ.get("RECEIVER_EMAIL", "")

# 要监控的网站列表
TARGETS = [
    {
        "name": "中国政府网-最新政策",
        "url": "https://www.gov.cn/zhengce/zuixin/",
        "type": "gov_cn"
    },
    {
        "name": "国家能源局-最新文件",
        "url": "https://www.nea.gov.cn/policy/ds_40d365c13659452aa06cdb7268d6192e.json",
        "type": "nea_json"
    },
    {
        "name": "山东省政府网-政策文件",
        "url": "http://www.shandong.gov.cn/jpaas-jpolicy-console-server/interface/getPolicyByOrgId",
        "type": "shandong_api"
    }
]

# =====================================================================

def send_email(subject, content):
    if not SENDER_EMAIL or not SENDER_PASSWORD:
        print("未配置邮件发送者，跳过发送。")
        print(f"拟发送内容:\n{content}")
        return

    try:
        message = MIMEText(content, 'plain', 'utf-8')
        # 修复：QQ邮箱要求 From 必须包含发件人邮箱地址，且格式要标准
        # 格式：Header("昵称", 'utf-8') + " <邮箱>" 这种写法有时会有问题
        # 最稳妥的写法：直接用 formataddr 或者手动拼接字符串，但 Header 对象更安全
        
        # 方法1：标准 Header 构造
        message['From'] = Header("云端监控助手", 'utf-8')
        message['From'].append(f"<{SENDER_EMAIL}>", 'ascii')
        
        message['To'] = Header("接收者", 'utf-8')
        message['Subject'] = Header(subject, 'utf-8')
        
        server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, [RECEIVER_EMAIL], message.as_string())
        server.quit()
        print(f"邮件发送成功: {subject}")
    except Exception as e:
        print(f"邮件发送失败: {e}")

def get_today_str():
    return datetime.datetime.now().strftime('%Y-%m-%d')

def check_gov_cn(target):
    print(f"正在检查: {target['name']}...")
    new_items = []
    today = get_today_str()
    
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(target['url'], headers=headers)
        r.encoding = 'utf-8'
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # 中国政府网通常列表在 .news_box 或类似的结构中，但也可能变
        # 简单粗暴：遍历所有带日期的链接
        for a in soup.find_all('a'):
            text = a.get_text(strip=True)
            href = a.get('href')
            if not text or len(text) < 5: continue
            
            # 尝试在链接周围找日期
            # 1. 父级文本
            # 2. 兄弟文本
            date = ""
            context = ""
            if a.parent: context += a.parent.get_text()
            if a.parent and a.parent.next_sibling: 
                ns = a.parent.next_sibling
                context += ns.get_text() if hasattr(ns, 'get_text') else str(ns)
            
            match = re.search(r'(\d{4}-\d{2}-\d{2})', context)
            if match:
                date = match.group(1)
            
            # 只有当日期是今天（或者昨天，防止时区差异漏掉）才收录
            # 为了保险，我们检查最近2天
            if date >= (datetime.datetime.now() - datetime.timedelta(days=1)).strftime('%Y-%m-%d'):
                full_link = urljoin(target['url'], href)
                new_items.append(f"[{date}] {text}\n{full_link}")
                
    except Exception as e:
        print(f"检查失败: {e}")
        
    return list(set(new_items)) # 去重

def check_nea_json(target):
    print(f"正在检查: {target['name']}...")
    new_items = []
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(target['url'], headers=headers)
        data = r.json()
        
        cutoff_date = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
        
        if 'datasource' in data:
            for item in data['datasource']:
                date = item.get('publishTime', '')[:10]
                if date >= cutoff_date:
                    title = re.sub(r'<[^>]+>', '', item.get('title', item.get('showTitle', '')))
                    link = item.get('publishUrl', '')
                    new_items.append(f"[{date}] {title}\n{link}")
    except Exception as e:
        print(f"检查失败: {e}")
    return new_items

def check_shandong_api(target):
    print(f"正在检查: {target['name']}...")
    new_items = []
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        # 针对 col316573 的 orgId
        params = {
            'orgId': '6996bb672f434d0bb82c49a8c1bd6f98,40c399d272694553bb6d38feb5cb4362',
            'sortKey': 'publish_date'
        }
        data = {'pageNo': 1, 'pageSize': 15}
        r = requests.post(target['url'], headers=headers, params=params, data=data)
        res = r.json()
        
        cutoff_date = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
        
        if 'data' in res and 'list' in res['data']:
            for item in res['data']['list']:
                date = item.get('publishDate', '')
                if date >= cutoff_date:
                    title = item.get('title', '')
                    iid = item.get('iid', '')
                    link = f"http://www.shandong.gov.cn/jpaas-jpolicy-web-server/front/info/detail?iid={iid}"
                    new_items.append(f"[{date}] {title}\n{link}")
    except Exception as e:
        print(f"检查失败: {e}")
    return new_items

def main():
    print(f"开始运行云端监控: {datetime.datetime.now()}")
    all_news = []
    
    for target in TARGETS:
        if target['type'] == 'gov_cn':
            items = check_gov_cn(target)
        elif target['type'] == 'nea_json':
            items = check_nea_json(target)
        elif target['type'] == 'shandong_api':
            items = check_shandong_api(target)
        else:
            items = []
            
        if items:
            all_news.append(f"=== {target['name']} ===")
            all_news.extend(items)
            all_news.append("") # 空行
            
    if all_news:
        content = "监测到今日（及昨日）有以下更新：\n\n" + "\n".join(all_news)
        print("发现更新，准备发送邮件...")
        send_email(f"【日报】政策更新提醒 {get_today_str()}", content)
    else:
        print("今日无新政策发布。")

if __name__ == "__main__":
    main()
