#!/usr/bin/env python3
"""
personal-ai-fde v1.0.0 回归测试。

覆盖四类安全/契约关键函数（不依赖真实会话日志，可在任何机器跑）：
  1. redact() 数据层 PII 脱敏 + 保留安全拦截原文
  2. redact_out() 展示层改写安全拦截原文
  3. build_review.esc HTML 转义（防引文注入）
  4. build_report.validate 渲染前强制校验（run_id 绑定 / evidence_refs 存在 / SOP 完整）
  5. worklens.build_changes 可比性护栏（同日重跑不判进步 / metric_version 变化不可比）
  6. classify_correction 提问不误判为纠错

运行： python3 -m pytest tests/test_skill_v1.py -q
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import parse_sessions as P          # noqa: E402
import worklens as W                # noqa: E402
import build_report as B            # noqa: E402
import build_review as R            # noqa: E402


# ---------------------------------------------------------------- 1. 数据层脱敏
def test_redact_email():
    assert P.redact("发给我 martin@example.com 谢谢") == "发给我 [邮箱] 谢谢"


def test_redact_phone():
    assert P.redact("电话 13812345678") == "电话 [手机号]"


def test_redact_idcard():
    assert P.redact("证件 110101199001011234") == "证件 [证件号]"


def test_redact_bank_card():
    assert P.redact("卡号 6222021234567890123") == "卡号 [卡号]"


def test_redact_bank_card_spaced():
    assert P.redact("卡号 6222 0212 3456 7890") == "卡号 [卡号]"


def test_redact_token_threshold_20():
    short = "abcdefghijklmnopqrst"          # 20 位：拦截
    assert P.redact("key " + short) == "key [长串]"
    ok = "a1b2c3d4e5"                        # 10 位：保留（可能是正常单词/编号）
    assert P.redact("code " + ok) == "code " + ok


def test_redact_url_query_params():
    out = P.redact("https://docs.qq.com/dop-api/opendoc?id=ABC&tab=BB")
    assert "ABC" not in out and "BB" not in out


def test_redact_data_layer_keeps_security_events():
    """数据层保留安全拦截原文，保证审计追溯（v1.0.0 语义）。"""
    raw = "tool failed: SANDBOX PERMISSION DENIED"
    assert P.redact(raw) == raw


# ---------------------------------------------------------------- 2. 展示层脱敏
def test_redact_out_replaces_security_events():
    out = P.redact_out("x Operation not permitted y")
    assert "Operation not permitted" not in out and "[系统拦截]" in out
    assert P.redact_out("x 安全策略拦截 y") == "x [系统拦截] y"


def test_redact_out_also_redacts_pii():
    assert P.redact_out("a@b.com Operation not permitted") == "[邮箱] [系统拦截]"


# ---------------------------------------------------------------- 3. HTML 转义
def test_esc_escapes_quotes_and_tags():
    s = R.esc('<img src=x onerror="alert(1)">')
    assert "<" not in s and '"' not in s.replace("&quot;", "")


# ---------------------------------------------------------------- 4. 渲染前强制校验
def _reset_errors():
    B.ERRORS.clear()
    B.WARN.clear()


def _base_scan_and_analysis():
    scan = {"schema": "3.1", "run_id": "20260930-220000",
            "evidence": [{"ref": "abcd1234#3"}]}
    analysis = {"schema": "3.1", "scan_run_id": "20260930-220000",
                "workflows": [], "findings": [],
                "opportunities": [{"id": "OP1", "evidence_refs": ["abcd1234#3"], "sop_id": "SOP1"}],
                "sops": [{"id": "SOP1", "steps": [{"step": "x"}], "trigger": "t", "inputs": "i",
                          "human_gates": "g", "exception_rules": "e", "acceptance": "a",
                          "trial": "r", "rollback": "b", "copy_prompt": "p",
                          "opportunity_ids": ["OP1"]}]}
    return scan, analysis


def test_validate_passes_on_consistent_analysis():
    _reset_errors()
    scan, analysis = _base_scan_and_analysis()
    B.validate(scan, analysis)
    assert B.ERRORS == []


def test_validate_rejects_run_id_mismatch():
    _reset_errors()
    scan, analysis = _base_scan_and_analysis()
    analysis["scan_run_id"] = "20990101-000000"
    B.validate(scan, analysis)
    assert any("scan_run_id 不匹配" in e for e in B.ERRORS)


def test_validate_rejects_missing_evidence_ref():
    _reset_errors()
    scan, analysis = _base_scan_and_analysis()
    analysis["opportunities"][0]["evidence_refs"] = ["deadbeef#9"]
    B.validate(scan, analysis)
    assert any("引用不存在" in e for e in B.ERRORS)


def test_validate_rejects_opportunity_without_sop():
    _reset_errors()
    scan, analysis = _base_scan_and_analysis()
    analysis["opportunities"][0]["sop_id"] = ""
    B.validate(scan, analysis)
    assert any("缺 SOP" in e for e in B.ERRORS)


# ---------------------------------------------------------------- 5. 周度可比性护栏
def _prev_snapshot(ts_offset_s, metric_version=None):
    return {"date": time.strftime("%Y-%m-%d"), "ts": time.time() + ts_offset_s,
            "scope_key": "全部工作区|7", "metric_version": metric_version or W.METRIC_VERSION,
            "metrics": {"work_sessions": 10, "correction_rate": 5.0}, "families": {}}


def test_build_changes_same_day_rerun_not_comparable():
    """同日重跑（间隔 <20h）不得判定进步。"""
    ch = W.build_changes(_prev_snapshot(-3600), {"work_sessions": 12, "correction_rate": 4.0}, [], time.time() * 1000)
    assert ch["comparable"] is False
    assert any("不足 20 小时" in n for n in ch.get("notes", []))


def test_build_changes_metric_version_mismatch_not_comparable():
    ch = W.build_changes(_prev_snapshot(-48 * 3600, metric_version="9.9"),
                         {"work_sessions": 12}, [], time.time() * 1000)
    assert ch["comparable"] is False


def test_build_changes_first_scan_is_baseline():
    ch = W.build_changes(None, {}, [], time.time() * 1000)
    assert ch["comparable"] is False and "首次扫描" in ch["status"]


# ---------------------------------------------------------------- 6. 纠错候选判定
def test_question_is_not_correction():
    assert P.classify_correction("还是重新再发一封呢？") == []


def test_real_rework_is_flagged():
    cats = P.classify_correction("这不是我要的方向，重新做")
    assert "方向" in cats or "返工" in cats


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
