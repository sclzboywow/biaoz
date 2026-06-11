#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
支付服务层
包含支付配置管理、支付账户绑定等功能
"""

import sqlite3
import json
import base64
import os
import time
from typing import Dict, Any, Optional
from urllib.parse import urlencode, quote_plus
from datetime import datetime
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_pem_private_key, load_pem_public_key
from cryptography.fernet import Fernet
from .db import init_sync_db

# 加密密钥，从环境变量获取
_raw_key = os.getenv('PAYMENT_ENCRYPTION_KEY')
_allow_tmp = (os.getenv('ALLOW_TEMP_ENCRYPTION_KEY') or '').lower() == 'true'
if not _raw_key and not _allow_tmp:
    raise RuntimeError('PAYMENT_ENCRYPTION_KEY missing - 请设置加密密钥或允许临时密钥')
if not _raw_key and _allow_tmp:
    _raw_key = Fernet.generate_key().decode()
    print("警告: 使用临时加密密钥，生产环境请设置 PAYMENT_ENCRYPTION_KEY")
ENCRYPTION_KEY = _raw_key.encode() if isinstance(_raw_key, str) else _raw_key

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resolve_key_path(path: str) -> str:
    if not path:
        return path
    if os.path.isabs(path) and os.path.exists(path):
        return path
    candidate = os.path.join(_PROJECT_ROOT, path)
    if os.path.exists(candidate):
        return candidate
    return path


def encrypt_sensitive_data(data: str) -> str:
    """加密敏感数据"""
    if not data:
        return ""
    try:
        f = Fernet(ENCRYPTION_KEY)
        encrypted_data = f.encrypt(data.encode())
        return base64.b64encode(encrypted_data).decode()
    except Exception as e:
        print(f"加密失败: {e}")
        return data

def decrypt_sensitive_data(encrypted_data: str) -> str:
    """解密敏感数据"""
    if not encrypted_data:
        return ""
    try:
        f = Fernet(ENCRYPTION_KEY)
        decoded_data = base64.b64decode(encrypted_data.encode())
        decrypted_data = f.decrypt(decoded_data)
        return decrypted_data.decode()
    except Exception as e:
        print(f"解密失败: {e}")
        return encrypted_data

def load_platform_payment_config(provider: str) -> Optional[Dict[str, str]]:
    """加载平台支付配置

    优先从环境变量读取（路径或Base64），否则读取数据库加密存储。
    支持变量：
    - ALIPAY_PRIVATE_KEY_PATH / ALIPAY_PUBLIC_KEY_PATH（PEM 文件路径）
    - ALIPAY_PRIVATE_KEY_B64 / ALIPAY_PUBLIC_KEY_B64（PEM Base64 单行）
    - 仅当 provider == 'alipay' 时生效。
    """
    if provider == 'alipay':
        # 1) 路径优先
        priv_path = _resolve_key_path(os.getenv('ALIPAY_PRIVATE_KEY_PATH') or '')
        pub_path = _resolve_key_path(os.getenv('ALIPAY_PUBLIC_KEY_PATH') or '')
        if priv_path and pub_path and os.path.exists(priv_path) and os.path.exists(pub_path):
            try:
                with open(priv_path, 'r', encoding='utf-8') as f:
                    priv = f.read()
                with open(pub_path, 'r', encoding='utf-8') as f:
                    pub = f.read()
                return {"public_key": pub, "private_key": priv, "status": "active", "source": "env:path"}
            except Exception as e:
                print(f"读取支付宝密钥文件失败: {e}")
        # 2) Base64 其次
        priv_b64 = os.getenv('ALIPAY_PRIVATE_KEY_B64')
        pub_b64 = os.getenv('ALIPAY_PUBLIC_KEY_B64')
        if priv_b64 and pub_b64:
            try:
                priv = base64.b64decode(priv_b64).decode('utf-8')
                pub = base64.b64decode(pub_b64).decode('utf-8')
                return {"public_key": pub, "private_key": priv, "status": "active", "source": "env:b64"}
            except Exception as e:
                print(f"解码支付宝密钥Base64失败: {e}")
    db_path = init_sync_db()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT public_key, private_key, status
            FROM platform_payment_configs
            WHERE provider = ? AND status = 'active'
        ''', (provider,))
        
        row = cursor.fetchone()
        if not row:
            return None
        
        public_key, private_key, status = row
        
        return {
            "public_key": decrypt_sensitive_data(public_key),
            "private_key": decrypt_sensitive_data(private_key),
            "status": status
        }
    except Exception as e:
        print(f"加载平台支付配置失败: {e}")
        return None
    finally:
        conn.close()

def save_platform_payment_config(provider: str, public_key: str, private_key: str, admin_id: str = "system") -> Dict[str, Any]:
    """保存平台支付配置"""
    # 导入风控服务
    from .risk_service import check_rate_limit
    
    # 检查频控（管理员操作限制）
    rate_limit_result = check_rate_limit(admin_id, 'payment_config')
    if not rate_limit_result.get('allowed', False):
        return {"status": "error", "message": rate_limit_result.get('message', '操作过于频繁')}
    
    db_path = init_sync_db()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # 检查是否已存在
        cursor.execute('SELECT id FROM platform_payment_configs WHERE provider = ?', (provider,))
        existing = cursor.fetchone()
        
        if existing:
            # 更新现有配置
            cursor.execute('''
                UPDATE platform_payment_configs 
                SET public_key = ?, private_key = ?, updated_at = ?, status = 'active'
                WHERE provider = ?
            ''', (
                encrypt_sensitive_data(public_key),
                encrypt_sensitive_data(private_key),
                time.time(),
                provider
            ))
            message = "payment config updated"
        else:
            # 创建新配置
            cursor.execute('''
                INSERT INTO platform_payment_configs (provider, public_key, private_key, status)
                VALUES (?, ?, ?, 'active')
            ''', (
                provider,
                encrypt_sensitive_data(public_key),
                encrypt_sensitive_data(private_key)
            ))
            message = "payment config created"
        
        conn.commit()
        return {"status": "success", "message": message}
        
    except Exception as exc:
        conn.rollback()
        return {"status": "error", "message": str(exc)}
    finally:
        conn.close()

def bind_payment_account(user_id: str, provider: str, account_no: str, 
                       account_name: Optional[str] = None) -> Dict[str, Any]:
    """
    绑定支付账户，支持支付宝等支付渠道
    密钥完全从平台配置中获取，用户只需提供账户信息
    """
    if not user_id or not provider or not account_no:
        return {"status": "error", "message": "missing parameters"}

    provider = provider.lower()

    # 检查平台是否已配置该支付渠道
    platform_config = load_platform_payment_config(provider)
    if not platform_config:
        return {"status": "error", "message": f"platform not configured for {provider}"}

    db_path = init_sync_db()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        cursor.execute('''
            INSERT INTO payment_accounts (user_id, provider, account_no, account_name, status)
            VALUES (?, ?, ?, ?, 'pending')
        ''', (user_id, provider, account_no, account_name))
        
        conn.commit()
        return {"status": "success", "message": "payment account bound"}
        
    except Exception as exc:
        conn.rollback()
        return {"status": "error", "message": str(exc)}
    finally:
        conn.close()

def process_payment_transaction(provider: str, amount: float, order_id: str) -> Dict[str, Any]:
    """
    处理支付交易的示例函数
    展示如何使用平台配置进行支付操作
    """
    payment_config = load_platform_payment_config(provider)
    
    if not payment_config:
        return {
            "status": "error",
            "message": f"未找到支付配置: {provider}"
        }
    
    public_key = payment_config["public_key"]
    private_key = payment_config["private_key"]
    
    print(f"使用平台配置处理支付: {provider}, 金额: {amount}, 订单: {order_id}")
    # 注意：不输出密钥信息，避免敏感数据泄露
    
    # 这里可以集成真实的支付SDK
    # 例如支付宝SDK、微信支付SDK等
    
    return {
        "status": "success",
        "message": "支付处理完成",
        "payment_config": {
            "provider": provider,
            "amount": amount,
            "order_id": order_id,
            "has_valid_keys": bool(public_key and private_key)
        }
    }


# =============== Alipay：页面支付、异步通知、主动查单 ===============

def _rsa2_sign(content: str, private_key_pem: str) -> str:
    key = load_pem_private_key(private_key_pem.encode('utf-8'), password=None)
    signature = key.sign(
        content.encode('utf-8'),
        padding.PKCS1v15(),
        hashes.SHA256()
    )
    return base64.b64encode(signature).decode('utf-8')


def _rsa2_verify(content: str, signature_b64: str, public_key_pem: str) -> bool:
    try:
        key = load_pem_public_key(public_key_pem.encode('utf-8'))
        signature = base64.b64decode(signature_b64)
        key.verify(
            signature,
            content.encode('utf-8'),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return True
    except Exception as e:
        print(f"支付宝验签失败: {e}")
        return False


def _notify_unsigned_string(params: Dict[str, Any]) -> str:
    items = [
        (k, params[k])
        for k in sorted(params.keys())
        if k not in ('sign', 'sign_type') and params[k] is not None and str(params[k]) != ''
    ]
    return "&".join([f"{k}={v}" for k, v in items])


def verify_alipay_notify_params(params: Dict[str, Any]) -> bool:
    """验证支付宝异步通知 RSA2 签名。"""
    sign = params.get('sign')
    if not sign:
        return False

    cfg = load_platform_payment_config('alipay') or {}
    alipay_public_key = (cfg.get('public_key') or '').strip()
    if not alipay_public_key:
        return False

    expected_app_id = (os.getenv('ALIPAY_APP_ID') or '').strip()
    if expected_app_id and params.get('app_id') != expected_app_id:
        print(f"支付宝 notify app_id 不匹配: {params.get('app_id')}")
        return False

    unsigned = _notify_unsigned_string(params)
    return _rsa2_verify(unsigned, sign, alipay_public_key)


def process_alipay_async_notify(params: Dict[str, Any]) -> Dict[str, Any]:
    """处理支付宝异步通知，返回业务处理结果。"""
    if not verify_alipay_notify_params(params):
        return {"status": "error", "message": "sign verify failed"}

    trade_status = (params.get('trade_status') or '').strip()
    if trade_status not in ('TRADE_SUCCESS', 'TRADE_FINISHED'):
        return {"status": "ignore", "message": f"trade_status={trade_status or 'empty'}"}

    out_trade_no = (params.get('out_trade_no') or '').strip()
    total_amount = params.get('total_amount')
    if not out_trade_no or total_amount is None:
        return {"status": "error", "message": "missing out_trade_no or total_amount"}

    try:
        amount_cents = int(round(float(total_amount) * 100))
    except (TypeError, ValueError):
        return {"status": "error", "message": "invalid total_amount"}

    if out_trade_no.startswith("T"):
        from library.service import fulfill_ticket_order, get_ticket_order_by_no

        order = get_ticket_order_by_no(out_trade_no)
        if not order:
            return {"status": "error", "message": "ticket order not found"}
        if int(order.get("amount_cent") or 0) != amount_cents:
            return {"status": "error", "message": "amount mismatch"}

        trade_no = (params.get('trade_no') or '').strip() or None
        result = fulfill_ticket_order(out_trade_no, trade_no)
        if result.get("status") == "success":
            _notify_bot_ticket_paid(result)
        return result

    from .order_service import process_payment_callback

    result = process_payment_callback(
        out_trade_no,
        'success',
        amount_cents,
        message='alipay_notify',
    )
    return result


def _notify_bot_ticket_paid(result: Dict[str, Any]) -> None:
    url = (os.getenv("BOT_TICKET_NOTIFY_URL") or "http://127.0.0.1:8765/internal/ticket-paid").strip()
    secret = (os.getenv("BOT_INTERNAL_SECRET") or "").strip()
    if not url:
        return
    try:
        import requests

        headers = {"X-Internal-Secret": secret} if secret else {}
        requests.post(url, json=result, headers=headers, timeout=5)
    except Exception as e:
        print(f"[ticket notify bot] failed: {e}")


def _ordered_query(params: Dict[str, Any]) -> str:
    # 以 key 的字典序排序，值保持原文，不做 url 编码
    items = [
        (k, params[k])
        for k in sorted(params.keys())
        if k != 'sign' and params[k] is not None and str(params[k]) != ''
    ]
    return "&".join([f"{k}={v}" for k, v in items])


def _encode_alipay_form(params: Dict[str, Any]) -> bytes:
    body = urlencode(
        {k: params[k] for k in params},
        quote_via=quote_plus,
        encoding='utf-8',
    )
    return body.encode('utf-8')


def _build_alipay_get_url(params: Dict[str, Any], gateway: str) -> str:
    query = urlencode(
        {k: params[k] for k in params},
        quote_via=quote_plus,
        encoding='utf-8',
    )
    return f"{gateway}?{query}"


def _alipay_post(params: Dict[str, Any], gateway: str):
    import requests

    headers = {'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'}
    return requests.post(
        gateway,
        data=_encode_alipay_form(params),
        headers=headers,
        timeout=15,
    )

def _alipay_common_fields(method: str, *, include_return_url: bool = False) -> Dict[str, Any]:
    app_id = os.getenv('ALIPAY_APP_ID') or ''
    if not app_id:
        raise ValueError('missing ALIPAY_APP_ID')
    params: Dict[str, Any] = {
        'app_id': app_id,
        'method': method,
        'format': 'JSON',
        'charset': 'utf-8',
        'sign_type': 'RSA2',
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'version': '1.0',
    }
    noti = (os.getenv('PAY_NOTIFY_URL') or '').strip()
    if noti:
        params['notify_url'] = noti
    if include_return_url:
        ret = (os.getenv('PAY_RETURN_URL') or '').strip()
        if ret:
            params['return_url'] = ret
    return params


def _sign_alipay_params(params: Dict[str, Any], private_key: str) -> Dict[str, Any]:
    signed = dict(params)
    unsigned = _ordered_query(signed)
    signed['sign'] = _rsa2_sign(unsigned, private_key)
    return signed


def create_alipay_precreate_pay(subject: str, total_amount: float, out_trade_no: str) -> Dict[str, Any]:
    """当面付-扫码支付（alipay.trade.precreate），返回 qr_code 供机器人生成二维码。

    若配置 PAY_NOTIFY_URL，下单时会携带 notify_url 供支付宝异步通知。
    返回: { status, pay_url, qr_code, gateway, notify_url?, trade_method }
    """
    try:
        cfg = load_platform_payment_config('alipay') or {}
        private_key = (cfg.get('private_key') or '').strip()
        if not private_key:
            return {"status": "error", "message": "missing private key"}

        product_code = (os.getenv('ALIPAY_PRODUCT_CODE') or 'FACE_TO_FACE_PAYMENT').strip()
        timeout_express = (os.getenv('ALIPAY_TIMEOUT_EXPRESS') or '10m').strip()
        gateway = os.getenv('ALIPAY_GATEWAY') or 'https://openapi.alipay.com/gateway.do'

        params = _alipay_common_fields('alipay.trade.precreate')
        biz_content = {
            'out_trade_no': out_trade_no,
            'total_amount': str(round(float(total_amount), 2)),
            'subject': subject,
            'product_code': product_code,
        }
        if timeout_express:
            biz_content['timeout_express'] = timeout_express
        params['biz_content'] = json.dumps(biz_content, ensure_ascii=False, separators=(',', ':'))
        params = _sign_alipay_params(params, private_key)

        resp = _alipay_post(params, gateway)
        if not resp.ok:
            return {"status": "error", "message": resp.text}
        data = resp.json()
        body = data.get('alipay_trade_precreate_response') or {}
        code = str(body.get('code') or '')
        if code != '10000':
            return {
                "status": "error",
                "message": body.get('sub_msg') or body.get('msg') or 'precreate failed',
                "raw": body,
            }
        qr_code = (body.get('qr_code') or '').strip()
        if not qr_code:
            return {"status": "error", "message": "missing qr_code", "raw": body}
        noti = (os.getenv('PAY_NOTIFY_URL') or '').strip()
        result = {
            "status": "success",
            "pay_url": qr_code,
            "qr_code": qr_code,
            "gateway": gateway,
            "trade_method": "precreate",
        }
        if noti:
            result["notify_url"] = noti
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}


def create_alipay_pay(subject: str, total_amount: float, out_trade_no: str) -> Dict[str, Any]:
    """按 ALIPAY_TRADE_METHOD 选择支付方式。

    - precreate / face_to_face / f2f: 当面付扫码（默认）
    - page / page_pay: 电脑网站支付
    """
    method = (os.getenv('ALIPAY_TRADE_METHOD') or 'precreate').strip().lower()
    if method in {'page', 'page_pay', 'wap', 'web'}:
        result = create_alipay_page_pay(subject=subject, total_amount=total_amount, out_trade_no=out_trade_no)
        if result.get('status') == 'success':
            result['trade_method'] = 'page'
        return result
    return create_alipay_precreate_pay(subject=subject, total_amount=total_amount, out_trade_no=out_trade_no)


def create_alipay_page_pay(subject: str, total_amount: float, out_trade_no: str) -> Dict[str, Any]:
    """生成 PC 网页支付链接（FAST_INSTANT_TRADE_PAY）。

    若配置 PAY_NOTIFY_URL，下单时会携带 notify_url 供支付宝异步通知。
    返回: { status, pay_url, gateway, notify_url? }
    """
    try:
        cfg = load_platform_payment_config('alipay') or {}
        private_key = (cfg.get('private_key') or '').strip()
        if not private_key:
            return {"status": "error", "message": "missing private key"}

        app_id = os.getenv('ALIPAY_APP_ID') or ''
        if not app_id:
            return {"status": "error", "message": "missing ALIPAY_APP_ID"}
        gateway = os.getenv('ALIPAY_GATEWAY') or 'https://openapi.alipay.com/gateway.do'

        # 通用参数
        common = {
            'app_id': app_id,
            'method': 'alipay.trade.page.pay',
            'format': 'JSON',
            'charset': 'utf-8',
            'sign_type': 'RSA2',
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'version': '1.0',
        }
        # 仅当配置不为空时才附带 return/notify
        ret = (os.getenv('PAY_RETURN_URL') or '').strip()
        noti = (os.getenv('PAY_NOTIFY_URL') or '').strip()
        if ret:
            common['return_url'] = ret
        if noti:
            common['notify_url'] = noti
        biz_content = {
            'out_trade_no': out_trade_no,
            'product_code': 'FAST_INSTANT_TRADE_PAY',
            'total_amount': str(round(float(total_amount), 2)),
            'subject': subject,
            # 可按需扩展: 'timeout_express': '15m'
        }
        params = dict(common)
        params['biz_content'] = json.dumps(biz_content, ensure_ascii=False, separators=(',', ':'))

        # 签名
        unsigned = _ordered_query(params)
        sign = _rsa2_sign(unsigned, private_key)
        params['sign'] = sign

        # 生成最终 URL（参数需 UTF-8 url 编码，charset 保留在查询串中）
        pay_url = _build_alipay_get_url(params, gateway)
        result = {"status": "success", "pay_url": pay_url, "gateway": gateway}
        if noti:
            result["notify_url"] = noti
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}

def query_alipay_trade(out_trade_no: str) -> Dict[str, Any]:
    """服务端查询交易结果（alipay.trade.query）。返回 {status, paid, raw}。"""
    try:
        cfg = load_platform_payment_config('alipay') or {}
        private_key = (cfg.get('private_key') or '').strip()
        if not private_key:
            return {"status": "error", "message": "missing private key"}
        app_id = os.getenv('ALIPAY_APP_ID') or ''
        if not app_id:
            return {"status": "error", "message": "missing ALIPAY_APP_ID"}
        gateway = os.getenv('ALIPAY_GATEWAY') or 'https://openapi.alipay.com/gateway.do'

        common = {
            'app_id': app_id,
            'method': 'alipay.trade.query',
            'format': 'JSON',
            'charset': 'utf-8',
            'sign_type': 'RSA2',
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'version': '1.0',
        }
        biz_content = {
            'out_trade_no': out_trade_no,
        }
        params = dict(common)
        params['biz_content'] = json.dumps(biz_content, ensure_ascii=False, separators=(',', ':'))
        unsigned = _ordered_query(params)
        sign = _rsa2_sign(unsigned, private_key)
        params['sign'] = sign

        # 按官方要求使用 x-www-form-urlencoded POST（UTF-8 + charset 头）
        resp = _alipay_post(params, gateway)
        if not resp.ok:
            return {"status": "error", "message": resp.text}
        data = resp.json()
        body = data.get('alipay_trade_query_response') or {}
        code = str(body.get('code'))
        paid = (body.get('trade_status') == 'TRADE_SUCCESS')
        return {"status": "success" if code == '10000' else "error", "paid": paid, "raw": body}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def refund_alipay_trade(
    *,
    out_trade_no: str,
    refund_amount: float,
    out_request_no: str,
    trade_no: Optional[str] = None,
    refund_reason: str = "用户申请退款",
) -> Dict[str, Any]:
    """当面付/扫码支付退款（alipay.trade.refund）。

    返回: {status, fund_change, refund_fee, raw, out_request_no}
    """
    try:
        cfg = load_platform_payment_config('alipay') or {}
        private_key = (cfg.get('private_key') or '').strip()
        if not private_key:
            return {"status": "error", "message": "missing private key"}

        gateway = os.getenv('ALIPAY_GATEWAY') or 'https://openapi.alipay.com/gateway.do'
        params = _alipay_common_fields('alipay.trade.refund')
        biz_content: Dict[str, Any] = {
            'out_trade_no': out_trade_no,
            'refund_amount': f"{round(float(refund_amount), 2):.2f}",
            'out_request_no': out_request_no,
        }
        if trade_no:
            biz_content['trade_no'] = trade_no
        if refund_reason:
            biz_content['refund_reason'] = refund_reason
        params['biz_content'] = json.dumps(biz_content, ensure_ascii=False, separators=(',', ':'))
        params = _sign_alipay_params(params, private_key)

        resp = _alipay_post(params, gateway)
        if not resp.ok:
            return {"status": "error", "message": resp.text}
        data = resp.json()
        body = data.get('alipay_trade_refund_response') or {}
        code = str(body.get('code') or '')
        if code != '10000':
            return {
                "status": "error",
                "message": body.get('sub_msg') or body.get('msg') or 'refund failed',
                "raw": body,
                "out_request_no": out_request_no,
            }
        return {
            "status": "success",
            "fund_change": body.get('fund_change'),
            "refund_fee": body.get('refund_fee'),
            "trade_no": body.get('trade_no'),
            "out_trade_no": body.get('out_trade_no') or out_trade_no,
            "out_request_no": out_request_no,
            "raw": body,
        }
    except Exception as e:
        return {"status": "error", "message": str(e), "out_request_no": out_request_no}


def query_alipay_refund(out_request_no: str, *, out_trade_no: Optional[str] = None, trade_no: Optional[str] = None) -> Dict[str, Any]:
    """查询退款结果（alipay.trade.fastpay.refund.query）。"""
    try:
        cfg = load_platform_payment_config('alipay') or {}
        private_key = (cfg.get('private_key') or '').strip()
        if not private_key:
            return {"status": "error", "message": "missing private key"}

        gateway = os.getenv('ALIPAY_GATEWAY') or 'https://openapi.alipay.com/gateway.do'
        params = _alipay_common_fields('alipay.trade.fastpay.refund.query')
        biz_content: Dict[str, Any] = {'out_request_no': out_request_no}
        if out_trade_no:
            biz_content['out_trade_no'] = out_trade_no
        if trade_no:
            biz_content['trade_no'] = trade_no
        params['biz_content'] = json.dumps(biz_content, ensure_ascii=False, separators=(',', ':'))
        params = _sign_alipay_params(params, private_key)

        resp = _alipay_post(params, gateway)
        if not resp.ok:
            return {"status": "error", "message": resp.text}
        data = resp.json()
        body = data.get('alipay_trade_fastpay_refund_query_response') or {}
        code = str(body.get('code') or '')
        return {
            "status": "success" if code == '10000' else "error",
            "refund_status": body.get('refund_status'),
            "raw": body,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
