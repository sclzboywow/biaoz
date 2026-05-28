#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
国标电子书库采集脚本（目录页 + 详情页 + 阅读页 → SQLite）

采集字段（与前端/后端模型对齐）：
- 列表页：bookId, code, name, status（现行/废止等）
- 详情页：cover（sharePic）、publish、implement、detailUrl
- 阅读页：probationUrl、resourcePrefix（absolute_path_prefix）、tocJson（目录标题+页码）

落库表：tool/guobiao.sqlite3 -> standards
  id(PK), code, name, status, publish, implement, cover,
  detailUrl, probationUrl, resourcePrefix, tocJson, sublibId, pageIndex, crawledAt
  扩展元数据：publisher, issuingOrg, supervisingDept, draftingOrgsJson, edition, isbn, pages, price, ics, ccs, region
  PDF 推断与校验：pdfUrl, pdfVerified, pdfStatus, pdfBytes, pdfCheckedAt
"""

import re
import json
import time
import html as ihtml
import sqlite3
from datetime import datetime
from typing import List, Dict, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from tqdm import tqdm


LIST_URLS = [
    "https://ebook.chinabuilding.com.cn/zbooklib/sublibBook/resultlist?SiteID=1&viewType=imgView&sublibID=2118&sortType=Default&abolish=&indexInfor=&PageIndex={page_index}",
    "https://ebook.chinabuilding.com.cn/zbooklib/sublibBook/resultlist?SiteID=1&viewType=imgView&sublibID=2246&sortType=Default&abolish=&indexInfor=&PageIndex={page_index}",
    "https://ebook.chinabuilding.com.cn/zbooklib/sublibBook/resultlist?SiteID=1&viewType=imgView&sublibID=2398&sortType=Default&abolish=&indexInfor=&PageIndex={page_index}",
    "https://ebook.chinabuilding.com.cn/zbooklib/sublibBook/resultlist?SiteID=1&viewType=imgView&sublibID=2441&sortType=Default&abolish=&indexInfor=&PageIndex={page_index}",
    "https://ebook.chinabuilding.com.cn/zbooklib/sublibBook/resultlist?SiteID=1&viewType=imgView&sublibID=2481&sortType=Default&abolish=&indexInfor=&PageIndex={page_index}",
]

# 预估页数（如需，后续可改为自动探测）
LIST_PAGES = [82, 349, 1867, 28, 82]


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Connection": "keep-alive",
    })
    # 禁用代理
    s.proxies = {
        'http': None,
        'https': None,
    }
    retry = Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s


def parse_title(full_title: str) -> Optional[Tuple[str, str]]:
    """从列表标题中解析 编号:名称，兼容中英文冒号。"""
    m = re.match(r"^\s*([^:：]+)\s*[:：]\s*(.+)$", full_title.strip())
    if not m:
        return None
    return m.group(1).strip(), m.group(2).strip()


def parse_list_items(html: str) -> List[Dict]:
    """从列表页 HTML 提取 bookID、full_title、status 文本。"""
    items = []
    # 尽量局部匹配，降低结构变动影响
    pattern = re.compile(
        r'<div class="img-search-list[\s\S]*?<h4 class="search-tit[\s\S]*?<a[^>]+href="[^"]*bookID=(\d+)"[^>]*>([\s\S]*?)</a>[\s\S]*?<span class="(active|abolish)">([\s\S]*?)</span>',
        re.IGNORECASE)
    for m in pattern.finditer(html):
        book_id = m.group(1)
        full_title = ihtml.unescape(m.group(2)).strip()
        status_text = ihtml.unescape(m.group(4)).strip()
        items.append({
            "bookId": book_id,
            "fullTitle": full_title,
            "statusText": status_text,
        })
    return items


def fetch_detail_fields(sess: requests.Session, book_id: str) -> Dict:
    """抓取详情页字段：封面、发布日期、实施日期、shareUrl等。"""
    url = f"https://ebook.chinabuilding.com.cn/zbooklib/book/detail/show?SiteID=1&bookID={book_id}"
    out: Dict = {"detailUrl": url}
    try:
        r = sess.get(url, timeout=10)
        r.raise_for_status()
        html = r.text
    except requests.RequestException:
        return out

    # 封面（sharePic 变量）
    m_cover = re.search(r"var\s+sharePic\s*=\s*'([^']+)'", html)
    if m_cover:
        out["cover"] = m_cover.group(1)

    # 发布/实施日期（尽量宽松匹配 YYYY-MM-DD / YYYY-MM）
    def pick_date(label: str) -> Optional[str]:
        # 例如：发布日期：2024-07-18 或 发布日期：2024-07
        m = re.search(label + r"[^0-9]*(\d{4}[-/.]\d{1,2}(?:[-/.]\d{1,2})?)", html)
        return m.group(1).replace("/", "-").replace(".", "-") if m else None

    publish = pick_date("发布") or pick_date("出版")
    implement = pick_date("实施") or pick_date("生效")
    if publish:
        out["publish"] = publish
    if implement:
        out["implement"] = implement

    # 其他元数据（宽松标签匹配）
    def extract_label_value(labels: List[str], maxlen: int = 120) -> Optional[str]:
        for lb in labels:
            # 兼容：lb：</th><td>值；或 “lb：值” 纯文字；或 span/td 混排
            pat = re.compile(
                lb + r"\s*[:：]?\s*(?:</?[a-zA-Z0-9]+[^>]*>)*\s*([^<\r\n]{1," + str(maxlen) + r"})",
                re.IGNORECASE)
            m = pat.search(html)
            if m:
                return ihtml.unescape(m.group(1)).strip()
        return None

    out["publisher"] = extract_label_value(["出版社", "出版单位"])
    out["issuingOrg"] = extract_label_value(["发布单位", "批准单位", "主管部门"])
    out["supervisingDept"] = extract_label_value(["批准部门", "主管部门", "归口单位"])
    drafting = extract_label_value(["主编单位", "起草单位", "编制单位", "参编单位"])
    if drafting:
        # 拆分为数组，存 JSON
        parts = [p.strip() for p in re.split(r"[，、,;；\s]\s*", drafting) if p.strip()]
        if parts:
            out["draftingOrgsJson"] = json.dumps(parts, ensure_ascii=False)
    out["edition"] = extract_label_value(["版次", "版本", "修订版", "版号"])

    # ISBN / 页数 / 定价
    m_isbn = re.search(r"ISBN[^0-9Xx]*([0-9\-Xx]{6,20})", html)
    if m_isbn:
        out["isbn"] = m_isbn.group(1)
    m_pages = re.search(r"(页数|页码)[^0-9]{0,6}(\d{1,5})", html)
    if m_pages:
        out["pages"] = m_pages.group(2)
    m_price = re.search(r"(定价|价格)[^0-9]{0,6}([0-9]+(?:\.[0-9]{1,2})?)", html)
    if m_price:
        out["price"] = m_price.group(2)

    # ICS/CCS 分类号（若有）
    m_ics = re.search(r"ICS\s*[:：]?\s*([0-9A-Za-z\.\-]+)", html)
    if m_ics:
        out["ics"] = m_ics.group(1)
    # 可能以 CCS 或 中国标准分类号 出现
    m_ccs = re.search(r"CCS\s*[:：]?\s*([A-Z0-9\.]+)|中国标准分类号[^A-Z0-9]*([A-Z0-9\.]+)", html)
    if m_ccs:
        out["ccs"] = m_ccs.group(1) or m_ccs.group(2)

    return out


def fetch_probation_fields(sess: requests.Session, book_id: str) -> Dict:
    """抓取试读页：资源前缀、目录 toc。"""
    url = f"https://ebook.chinabuilding.com.cn/zbooklib/bookpdf/probation?SiteID=1&bookID={book_id}"
    out: Dict = {"probationUrl": url}
    try:
        r = sess.get(url, timeout=10)
        r.raise_for_status()
        html = r.text
    except requests.RequestException:
        return out

    # 资源前缀 absolute_path_prefix
    m_prefix = re.search(r'absolute_path_prefix\s*=\s*"([^"]+)"', html)
    if m_prefix:
        prefix = m_prefix.group(1)
        out["resourcePrefix"] = prefix
        # 依据规则：{prefix}{basename}1.page -> {prefix}{basename}.pdf
        m_first = re.search(re.escape(prefix) + r'([A-Za-z0-9_\-]+)1\.page', html)
        if m_first:
            base = m_first.group(1)
            pdf_from_first = f"{prefix}{base}.pdf"
            out.setdefault("pdfCandidates", []).append(pdf_from_first)

    # 目录提取：data-dest-detail="[10,&quot;Fit&quot;]" 的页码与标题
    toc = []
    for m in re.finditer(r'<a[^>]+data-dest-detail=\"\[(\d+),&quot;Fit&quot;\]\"[^>]*>(.*?)</a>', html):
        page = int(m.group(1))
        title = ihtml.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()
        if title:
            toc.append({"title": title, "page": page})
    if toc:
        out["tocJson"] = json.dumps(toc, ensure_ascii=False)
    return out


def init_db(db_path: str = "guobiao.sqlite3") -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS standards (
            id INTEGER PRIMARY KEY,
            code TEXT,
            name TEXT,
            status TEXT,
            publish TEXT,
            implement TEXT,
            cover TEXT,
            detailUrl TEXT,
            probationUrl TEXT,
            resourcePrefix TEXT,
            tocJson TEXT,
            sublibId INTEGER,
            pageIndex INTEGER,
            crawledAt TEXT
        )
        """
    )
    # 动态补充新列（向后兼容）
    ensure_cols = {
        "publisher": "TEXT",
        "issuingOrg": "TEXT",
        "supervisingDept": "TEXT",
        "draftingOrgsJson": "TEXT",
        "edition": "TEXT",
        "isbn": "TEXT",
        "pages": "TEXT",
        "price": "TEXT",
        "ics": "TEXT",
        "ccs": "TEXT",
        "region": "TEXT",
    }
    cur = conn.execute("PRAGMA table_info(standards)")
    cols = {row[1] for row in cur.fetchall()}
    for col, typ in ensure_cols.items():
        if col not in cols:
            conn.execute(f"ALTER TABLE standards ADD COLUMN {col} {typ}")
    # 追加保障：确保 PDF 相关列存在（避免上方 ensure_cols 未覆盖到时）
    for col, typ in (
        ("pdfUrl", "TEXT"),
        ("pdfVerified", "INTEGER"),
        ("pdfStatus", "INTEGER"),
        ("pdfBytes", "INTEGER"),
        ("pdfCheckedAt", "TEXT"),
    ):
        if col not in cols:
            try:
                conn.execute(f"ALTER TABLE standards ADD COLUMN {col} {typ}")
            except Exception:
                pass
    return conn


def upsert_standard(conn: sqlite3.Connection, rec: Dict) -> None:
    fields = [
        "id", "code", "name", "status", "publish", "implement", "cover",
        "detailUrl", "probationUrl", "resourcePrefix", "tocJson", "sublibId",
        "pageIndex", "crawledAt",
        # 扩展元数据
        "publisher", "issuingOrg", "supervisingDept", "draftingOrgsJson",
        "edition", "isbn", "pages", "price", "ics", "ccs", "region"
    ]
    values = [rec.get(k) for k in fields]
    conn.execute(
        f"""
        INSERT INTO standards ({', '.join(fields)})
        VALUES ({', '.join(['?']*len(fields))})
        ON CONFLICT(id) DO UPDATE SET
          code=excluded.code,
          name=excluded.name,
          status=excluded.status,
          publish=excluded.publish,
          implement=excluded.implement,
          cover=excluded.cover,
          detailUrl=excluded.detailUrl,
          probationUrl=excluded.probationUrl,
          resourcePrefix=excluded.resourcePrefix,
          tocJson=excluded.tocJson,
          sublibId=excluded.sublibId,
          pageIndex=excluded.pageIndex,
          crawledAt=excluded.crawledAt,
          publisher=excluded.publisher,
          issuingOrg=excluded.issuingOrg,
          supervisingDept=excluded.supervisingDept,
          draftingOrgsJson=excluded.draftingOrgsJson,
          edition=excluded.edition,
          isbn=excluded.isbn,
          pages=excluded.pages,
          price=excluded.price,
          ics=excluded.ics,
          ccs=excluded.ccs,
          region=excluded.region
        """
    , values)


def crawl_pages():
    sess = make_session()
    conn = init_db()

    total_pages = sum(LIST_PAGES)
    # 暂时禁用进度条以便查看调试信息
    # with tqdm(total=total_pages, desc="总体进度") as pbar_total:
    for url_idx, (base_url, total_pages) in enumerate(zip(LIST_URLS, LIST_PAGES), start=1):
        print(f"处理链接 {url_idx}/{len(LIST_URLS)}: {base_url}")
        # with tqdm(total=total_pages, desc=f"链接 {url_idx}/{len(LIST_URLS)}", leave=False) as pbar_url:
        # 从 base_url 参数中抽 sublibID 便于记录
        sublib_m = re.search(r"sublibID=(\d+)", base_url)
        sublib_id = int(sublib_m.group(1)) if sublib_m else None

        for page_index in range(1, total_pages + 1):
            url = base_url.format(page_index=page_index)
            print(f"正在请求: {url}")
            try:
                resp = sess.get(url, timeout=10)
                resp.raise_for_status()
                print(f"请求成功，状态码: {resp.status_code}, 内容长度: {len(resp.text)}")
            except requests.RequestException as e:
                print(f"请求失败: {e}")
                # pbar_url.update(1)
                # pbar_total.update(1)
                continue

            list_items = parse_list_items(resp.text)
            print(f"页面 {page_index} 解析到 {len(list_items)} 条记录")
            for it in list_items:
                parsed = parse_title(it["fullTitle"]) or (None, None)
                code, name = parsed
                if not code or not name:
                    continue

                book_id = int(it["bookId"])  # 主键
                status = it["statusText"]

                # 详情与试读补充
                detail = fetch_detail_fields(sess, str(book_id))
                probation = fetch_probation_fields(sess, str(book_id))

                rec = {
                    "id": book_id,
                    "code": code,
                    "name": name,
                    "status": status,
                    "publish": detail.get("publish"),
                    "implement": detail.get("implement"),
                    "cover": detail.get("cover"),
                    "detailUrl": detail.get("detailUrl"),
                    "probationUrl": probation.get("probationUrl"),
                    "resourcePrefix": probation.get("resourcePrefix"),
                    "tocJson": probation.get("tocJson"),
                    "sublibId": sublib_id,
                    "pageIndex": page_index,
                    "crawledAt": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                    # 扩展：详情元数据
                    "publisher": detail.get("publisher"),
                    "issuingOrg": detail.get("issuingOrg"),
                    "supervisingDept": detail.get("supervisingDept"),
                    "draftingOrgsJson": detail.get("draftingOrgsJson"),
                    "edition": detail.get("edition"),
                    "isbn": detail.get("isbn"),
                    "pages": detail.get("pages"),
                    "price": detail.get("price"),
                    "ics": detail.get("ics"),
                    "ccs": detail.get("ccs"),
                    "region": None,
                }

                # 依据规则获取 PDF 直链（若已在阅读页命中）
                pdf_candidates = probation.get("pdfCandidates") if isinstance(probation.get("pdfCandidates"), list) else []
                if pdf_candidates:
                    rec["pdfUrl"] = pdf_candidates[0]
                    print(f"推断PDF: {rec['pdfUrl']}")

                try:
                    upsert_standard(conn, rec)
                    conn.commit()
                    print(f"成功插入记录: {code} - {name}")
                    # 若存在推断的 PDF，则做轻量校验并获取文件大小
                    if rec.get("pdfUrl"):
                        try:
                            # 使用 HEAD 请求获取文件信息，不下载文件内容
                            headers = {"User-Agent": sess.headers.get("User-Agent", "")}
                            if rec.get("detailUrl"):
                                headers["Referer"] = rec["detailUrl"]
                            
                            # 先尝试 HEAD 请求
                            rpdf = sess.head(rec["pdfUrl"], headers=headers, timeout=10, allow_redirects=True)
                            status = rpdf.status_code
                            ok = status in (200, 206)
                            ctype = (rpdf.headers.get("Content-Type") or "").lower()
                            
                            # 如果 HEAD 请求失败，尝试 Range 请求
                            if not ok or not ("pdf" in ctype or ctype == "application/octet-stream"):
                                rpdf = sess.get(rec["pdfUrl"], headers={**headers, "Range": "bytes=0-0"}, 
                                              timeout=10, allow_redirects=True, stream=True)
                                status = rpdf.status_code
                                ok = status in (200, 206)
                                ctype = (rpdf.headers.get("Content-Type") or "").lower()
                            
                            if ok and ("pdf" in ctype or ctype == "application/octet-stream"):
                                # 获取文件大小
                                size_header = rpdf.headers.get("Content-Length")
                                size_int = None
                                
                                if size_header:
                                    try:
                                        size_int = int(size_header)
                                    except Exception:
                                        size_int = None
                                
                                # 如果 Content-Length 不可用，尝试从 Content-Range 推断
                                if size_int is None:
                                    content_range = rpdf.headers.get("Content-Range")
                                    if content_range and "/" in content_range:
                                        try:
                                            # Content-Range: bytes 0-0/1234567
                                            total_size = content_range.split("/")[-1]
                                            size_int = int(total_size)
                                        except Exception:
                                            size_int = None
                                
                                print(f"PDF文件大小: {size_int} bytes ({size_int/1024/1024:.1f} MB)" if size_int else "PDF文件大小: 未知")
                                
                                conn.execute(
                                    "UPDATE standards SET pdfUrl=?, pdfVerified=?, pdfStatus=?, pdfBytes=?, pdfCheckedAt=? WHERE id=?",
                                    (rec["pdfUrl"], 1, status, size_int, datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), rec["id"]) 
                                )
                                conn.commit()
                            else:
                                print(f"PDF验证失败: 状态码={status}, 类型={ctype}")
                                conn.execute(
                                    "UPDATE standards SET pdfUrl=?, pdfVerified=?, pdfStatus=?, pdfCheckedAt=? WHERE id=?",
                                    (rec["pdfUrl"], 0, status, datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), rec["id"]) 
                                )
                                conn.commit()
                        except Exception as e:
                            print(f"PDF校验异常: {e}")
                            # 忽略校验异常，保持基础数据
                            pass
                except Exception as e:
                    # 保底回滚，继续下一条
                    conn.rollback()
                    print(f"插入失败: {e}")
                    continue

            # pbar_url.update(1)
            # pbar_total.update(1)
            time.sleep(0.5)  # 适度放慢，降低被限频风险

    conn.close()
    print("\n爬取完成，数据已写入 SQLite：tool/guobiao.sqlite3 表 standards")


if __name__ == "__main__":
    crawl_pages()
