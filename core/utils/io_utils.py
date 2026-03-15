from __future__ import annotations

import json
from pathlib import Path

from core.dvc.schema import DataOverview, DvcScoreOutput


def format_data_overview(overview: DataOverview | None, verbose: bool = False) -> str:
    """データ取得概要を人間が読みやすいテキストに整形する。"""
    if overview is None:
        return "(データ概要なし)"
    lines: list[str] = []

    if overview.price_history:
        ph = overview.price_history
        status = "OK" if not ph.empty else "空"
        lines.append(f"[株価履歴] 行数={ph.rows} 期間={ph.date_min or '-'} ～ {ph.date_max or '-'} 直近終値={ph.last_close} ({status})")
        if verbose:
            lines.append(f"  カラム: {ph.columns}")

    if overview.benchmark:
        b = overview.benchmark
        status = "OK" if not b.empty else "空"
        lines.append(f"[ベンチマーク] 行数={b.rows} 期間={b.date_min or '-'} ～ {b.date_max or '-'} ({status})")
        if verbose:
            lines.append(f"  カラム: {b.columns}")

    if overview.fundamentals:
        f = overview.fundamentals
        lines.append(
            f"[ファンダメンタル] 銘柄名={f.long_name or '-'} セクター={f.sector or '-'} "
            f"BPS={f.book_value_per_share} EPS(TTM)={f.eps_ttm} 発行済み株数={f.shares_outstanding}"
        )

    if overview.sector_peers:
        sp = overview.sector_peers
        lines.append(
            f"[セクター・ピア] 解決セクター={sp.resolved_sector or '-'} "
            f"ピア数={sp.peer_count} (PB取得={sp.peer_pb_count}, PE取得={sp.peer_pe_count})"
        )
        if verbose and sp.peer_tickers:
            lines.append(f"  ティッカー: {sp.peer_tickers}")

    if verbose and overview.value_inputs:
        lines.append("[Value入力] " + json.dumps(overview.value_inputs, ensure_ascii=False))

    return "\n".join(lines)


def ensure_dir(path: str) -> None:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)


def save_output_json(output: DvcScoreOutput, path: str) -> None:
    p = Path(path)
    if p.parent:
        p.parent.mkdir(parents=True, exist_ok=True)
    # pydantic v2: model_dump_jsonにensure_asciiは存在しないため、自前でdumpする
    data = output.model_dump(mode="json")
    text = json.dumps(data, ensure_ascii=False, indent=2)
    try:
        p.write_text(text, encoding="utf-8")
    except OSError as e:
        raise OSError(f"JSON の書き込みに失敗しました: {p}: {e}") from e

