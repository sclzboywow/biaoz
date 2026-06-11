"""Refund helpers for payment_service.py (append if missing)."""

REFUND_FUNCTIONS = r'''
def refund_alipay_trade(
    *,
    out_trade_no: str,
    refund_amount: float,
    out_request_no: str,
    trade_no=None,
    refund_reason: str = "refund",
):
    """Alipay face-to-face refund (alipay.trade.refund). Returns to payer account."""
    try:
        cfg = load_platform_payment_config('alipay') or {}
        private_key = (cfg.get('private_key') or '').strip()
        if not private_key:
            return {"status": "error", "message": "missing private key"}

        gateway = os.getenv('ALIPAY_GATEWAY') or 'https://openapi.alipay.com/gateway.do'
        params = _alipay_common_fields('alipay.trade.refund')
        biz_content = {
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


def query_alipay_refund(out_request_no: str, *, out_trade_no=None, trade_no=None):
    """Query refund status (alipay.trade.fastpay.refund.query)."""
    try:
        cfg = load_platform_payment_config('alipay') or {}
        private_key = (cfg.get('private_key') or '').strip()
        if not private_key:
            return {"status": "error", "message": "missing private key"}

        gateway = os.getenv('ALIPAY_GATEWAY') or 'https://openapi.alipay.com/gateway.do'
        params = _alipay_common_fields('alipay.trade.fastpay.refund.query')
        biz_content = {'out_request_no': out_request_no}
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
'''
