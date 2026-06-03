from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
import time

# 设置Chrome选项
chrome_options = Options()
chrome_options.add_argument("--headless")  # 无头模式
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")

# 启动Chrome浏览器
service = Service('C:\Program Files\Google\Chrome\Application\chrome.exe')  # 替换为你的chromedriver路径
driver = webdriver.Chrome(service=service, options=chrome_options)

# 打开目标网址
url = "https://openstd.samr.gov.cn/bzgk/gb/std_list_type?p.p1=2&p.p90=circulation_date&p.p91=desc"
driver.get(url)

# 等待页面加载
time.sleep(5)  # 根据需要调整等待时间

# 获取标准列表
standards = driver.find_elements(By.TAG_NAME, 'tr')[1:]  # 跳过表头

# 提取信息
for standard in standards:
    columns = standard.find_elements(By.TAG_NAME, 'td')
    if len(columns) >= 7:  # 确保有足够的列
        standard_number = columns[1].text.strip()  # 标准号
        standard_name = columns[3].text.strip()    # 标准名称
        status = columns[2].text.strip()            # 是否采标
        publish_date = columns[5].text.strip()      # 发布日期
        implement_date = columns[6].text.strip()    # 实施日期

        print(f"标准号: {standard_number}, 标准名称: {standard_name}, 是否采标: {status}, 发布日期: {publish_date}, 实施日期: {implement_date}")
    else:
        print("行数据不完整，跳过该行。")

# 关闭浏览器
driver.quit()
