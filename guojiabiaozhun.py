import requests
import time
import pandas as pd
from tqdm import tqdm
import os

class StandardCrawler:
    def __init__(self, session_id, output_file='standards_data.xlsx'):
        self.base_url = "https://std.samr.gov.cn/gb"
        self.session = requests.Session()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Requested-With": "XMLHttpRequest",
            "Cookie": f"JSESSIONID={session_id}"  # 替换为有效的JSESSIONID
        }
        self.output_file = output_file
        self.seen_codes = set()  # 用于存储已见过的标准号
        self.all_records = []  # 用于存储所有记录

    def init_session(self):
        self.session.get(self.base_url, headers=self.headers)

    def get_standards_page(self, page=1, size=50):
        api_url = f"{self.base_url}/search/gbQueryPage"
        params = {
            "searchText": "",
            "ics": "",
            "state": "",
            "ISSUE_DATE": "",
            "sortOrder": "asc",
            "pageSize": str(size),
            "pageNumber": str(page),
            "_": str(int(time.time() * 1000))  # 添加时间戳以防止缓存
        }
        
        response = self.session.get(api_url, headers=self.headers, params=params)
        
        if response.status_code != 200:
            print(f"请求失败，状态码: {response.status_code}")
            return {}
        
        return response.json()

    def load_existing_data(self):
        """加载已存在的数据以支持断点续传"""
        if os.path.exists(self.output_file):
            df = pd.read_excel(self.output_file)
            for _, row in df.iterrows():
                self.seen_codes.add(row['标准号'])

    def check_data(self):
        self.load_existing_data()  # 加载已存在的数据
        
        # 获取第一页以确定总记录数
        first_page = self.get_standards_page(1)
        total = first_page.get('total', 0)
        total_pages = (total + 49) // 50  # 计算总页数

        print(f"开始采集数据，总记录数: {total}, 总页数: {total_pages}")

        # 处理所有页面
        with tqdm(total=total_pages, desc="采集进度") as pbar:
            for page in range(1, total_pages + 1):
                data = self.get_standards_page(page, size=50)
                if not data or 'rows' not in data:
                    print("未获取到有效数据")
                    break
                
                current_records = data['rows']
                
                for record in current_records:
                    if 'id' not in record:
                        continue
                    
                    code = record.get('C_STD_CODE', '未知代码')
                    name = record.get('C_C_NAME', '未知名称')
                    status = record.get('STATE', '未知状态')
                    detail_url = f"{self.base_url}/search/gbDetailed?id={record['id']}"
                    
                    if code not in self.seen_codes:
                        self.seen_codes.add(code)
                        self.all_records.append({
                            '标准号': code,
                            '标准中文名称': name,
                            '标准状态': status,
                            '下载地址': detail_url
                        })

                pbar.update(1)  # 更新进度条
                time.sleep(0.5)  # 适当延迟，避免请求过快

        self.save_to_excel()

    def save_to_excel(self):
        df = pd.DataFrame(self.all_records)
        df.to_excel(self.output_file, index=False)
        print(f"数据已保存到 {self.output_file}")

if __name__ == "__main__":
    session_id = "YOUR_SESSION_ID"  # 替换为有效的JSESSIONID
    crawler = StandardCrawler(session_id)
    crawler.init_session()
    crawler.check_data()  # 自动下载所有页面的数据
