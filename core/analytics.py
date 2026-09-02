import json
import csv
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Tuple, Optional, Any


def bucket_records_by_time(
    records: List[Tuple[Optional[datetime], int, int, int]],
    timeframe: str = "7d",
    ref_time: Optional[datetime] = None,
    use_local_time: bool = True
) -> List[Dict[str, Any]]:
    """
    Aggregates a list of (datetime, prompt, thinking, candidates) records into
    ordered time buckets based on the requested timeframe:
      - '5h': 10 thirty-minute buckets covering the 5-hour rolling rate-limit window
      - '24h' or 'hourly': 24 one-hour buckets covering the last 24 hours
      - '7d' or 'daily_7': 7 one-day buckets covering the last 7 days
      - '30d' or 'daily_30': 30 one-day buckets covering the last 30 days
      - 'month' or 'monthly': 12 one-month buckets covering the last 12 months
      - 'year' or 'yearly': multi-year buckets
      - 'session': step-by-step sequential timeline for a single session
    """
    if ref_time is not None:
        now = ref_time
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        if use_local_time:
            now = now.astimezone()
    else:
        now = datetime.now().astimezone() if use_local_time else datetime.now(timezone.utc)

    # Filter out empty or None-timestamp records (unless in session mode)
    valid_records: List[Tuple[datetime, int, int, int]] = []
    for dt, p, th, c in records:
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if use_local_time:
                dt = dt.astimezone()
            valid_records.append((dt, p, th, c))
        elif timeframe == "session" and (p + th + c > 0):
            valid_records.append((now, p, th, c))

    timeframe_norm = timeframe.lower().strip()
    buckets: List[Dict[str, Any]] = []

    # 0. 5-HOUR TIMEFRAME (11 thirty-minute buckets covering past 5h + current ongoing 30m block)
    if timeframe_norm in ("5h", "5_hours", "5hour"):
        curr_min = 0 if now.minute < 30 else 30
        curr_dt = now.replace(minute=curr_min, second=0, microsecond=0)
        start_dt = curr_dt - timedelta(hours=5)
        bucket_dict: Dict[str, Dict[str, Any]] = {}

        # 11 buckets from start_dt to curr_dt (e.g. at 13:06 -> 08:00 to 13:00)
        for i in range(11):
            b_dt = start_dt + timedelta(minutes=30 * i)
            next_b_dt = b_dt + timedelta(minutes=30)
            key = b_dt.strftime("%Y-%m-%d %H:%M")
            lbl = b_dt.strftime("%H:%M")
            bucket_dict[key] = {
                "key": key,
                "label": lbl,
                "full_label": f"{b_dt.strftime('%b %d, %H:%M')} - {next_b_dt.strftime('%H:%M')}",
                "dt": b_dt,
                "prompt": 0,
                "thinking": 0,
                "candidates": 0,
                "total": 0,
                "count": 0,
            }

        for dt, p, th, c in valid_records:
            if dt >= start_dt:
                b_min = 0 if dt.minute < 30 else 30
                b_dt = dt.replace(minute=b_min, second=0, microsecond=0)
                key = b_dt.strftime("%Y-%m-%d %H:%M")
                if key in bucket_dict:
                    bucket_dict[key]["prompt"] += p
                    bucket_dict[key]["thinking"] += th
                    bucket_dict[key]["candidates"] += c
                    bucket_dict[key]["total"] += (p + th + c)
                    bucket_dict[key]["count"] += 1

        buckets = list(bucket_dict.values())

    # 1. 24-HOUR / HOURLY TIMEFRAME (24 one-hour buckets covering past 23h + current ongoing hour)
    elif timeframe_norm in ("24h", "hourly", "1d"):
        curr_hour = now.replace(minute=0, second=0, microsecond=0)
        start_hour = curr_hour - timedelta(hours=23)
        bucket_dict: Dict[str, Dict[str, Any]] = {}

        for i in range(24):
            b_dt = start_hour + timedelta(hours=i)
            next_b_dt = b_dt + timedelta(hours=1)
            key = b_dt.strftime("%Y-%m-%d %H:00")
            lbl = b_dt.strftime("%H:%M")
            bucket_dict[key] = {
                "key": key,
                "label": lbl,
                "full_label": f"{b_dt.strftime('%b %d, %H:00')} - {next_b_dt.strftime('%H:00')}",
                "dt": b_dt,
                "prompt": 0,
                "thinking": 0,
                "candidates": 0,
                "total": 0,
                "count": 0,
            }

        for dt, p, th, c in valid_records:
            if dt >= start_hour:
                b_dt = dt.replace(minute=0, second=0, microsecond=0)
                key = b_dt.strftime("%Y-%m-%d %H:00")
                if key in bucket_dict:
                    bucket_dict[key]["prompt"] += p
                    bucket_dict[key]["thinking"] += th
                    bucket_dict[key]["candidates"] += c
                    bucket_dict[key]["total"] += (p + th + c)
                    bucket_dict[key]["count"] += 1

        buckets = list(bucket_dict.values())

    # 2. 7-DAY / DAILY TIMEFRAME
    elif timeframe_norm in ("7d", "daily", "daily_7"):
        start_day = (now - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)
        bucket_dict = {}

        for i in range(7):
            b_dt = start_day + timedelta(days=i)
            key = b_dt.strftime("%Y-%m-%d")
            lbl = b_dt.strftime("%a %d")  # e.g. "Sun 30"
            bucket_dict[key] = {
                "key": key,
                "label": lbl,
                "full_label": b_dt.strftime("%A, %b %d, %Y"),
                "dt": b_dt,
                "prompt": 0,
                "thinking": 0,
                "candidates": 0,
                "total": 0,
                "count": 0,
            }

        for dt, p, th, c in valid_records:
            if dt >= start_day:
                key = dt.strftime("%Y-%m-%d")
                if key in bucket_dict:
                    bucket_dict[key]["prompt"] += p
                    bucket_dict[key]["thinking"] += th
                    bucket_dict[key]["candidates"] += c
                    bucket_dict[key]["total"] += (p + th + c)
                    bucket_dict[key]["count"] += 1

        buckets = list(bucket_dict.values())

    # 3. 30-DAY / DAILY TIMEFRAME
    elif timeframe_norm in ("30d", "daily_30", "1m"):
        start_day = (now - timedelta(days=29)).replace(hour=0, minute=0, second=0, microsecond=0)
        bucket_dict = {}

        for i in range(30):
            b_dt = start_day + timedelta(days=i)
            key = b_dt.strftime("%Y-%m-%d")
            lbl = b_dt.strftime("%d")  # e.g. "30"
            bucket_dict[key] = {
                "key": key,
                "label": lbl,
                "full_label": b_dt.strftime("%b %d, %Y"),
                "dt": b_dt,
                "prompt": 0,
                "thinking": 0,
                "candidates": 0,
                "total": 0,
                "count": 0,
            }

        for dt, p, th, c in valid_records:
            if dt >= start_day:
                key = dt.strftime("%Y-%m-%d")
                if key in bucket_dict:
                    bucket_dict[key]["prompt"] += p
                    bucket_dict[key]["thinking"] += th
                    bucket_dict[key]["candidates"] += c
                    bucket_dict[key]["total"] += (p + th + c)
                    bucket_dict[key]["count"] += 1

        buckets = list(bucket_dict.values())

    # 4. MONTHLY / 12 MONTHS TIMEFRAME
    elif timeframe_norm in ("month", "monthly", "12m", "1y"):
        # Last 12 months
        cur_year, cur_month = now.year, now.month
        bucket_dict = {}

        months_list = []
        for i in range(11, -1, -1):
            y = cur_year
            m = cur_month - i
            while m <= 0:
                m += 12
                y -= 1
            dt_m = datetime(y, m, 1, tzinfo=now.tzinfo)
            months_list.append(dt_m)

        for dt_m in months_list:
            key = dt_m.strftime("%Y-%m")
            lbl = dt_m.strftime("%b %y")
            bucket_dict[key] = {
                "key": key,
                "label": lbl,
                "full_label": dt_m.strftime("%B %Y"),
                "dt": dt_m,
                "prompt": 0,
                "thinking": 0,
                "candidates": 0,
                "total": 0,
                "count": 0,
            }

        for dt, p, th, c in valid_records:
            key = dt.strftime("%Y-%m")
            if key in bucket_dict:
                bucket_dict[key]["prompt"] += p
                bucket_dict[key]["thinking"] += th
                bucket_dict[key]["candidates"] += c
                bucket_dict[key]["total"] += (p + th + c)
                bucket_dict[key]["count"] += 1

        buckets = list(bucket_dict.values())

    # 5. YEARLY TIMEFRAME
    elif timeframe_norm in ("year", "yearly", "all_years"):
        years_set = set()
        for dt, _, _, _ in valid_records:
            years_set.add(dt.year)
        years_set.add(now.year)
        sorted_years = sorted(list(years_set))

        bucket_dict = {}
        for y in sorted_years:
            key = str(y)
            dt_y = datetime(y, 1, 1, tzinfo=now.tzinfo)
            bucket_dict[key] = {
                "key": key,
                "label": str(y),
                "full_label": f"Year {y}",
                "dt": dt_y,
                "prompt": 0,
                "thinking": 0,
                "candidates": 0,
                "total": 0,
                "count": 0,
            }

        for dt, p, th, c in valid_records:
            key = str(dt.year)
            if key in bucket_dict:
                bucket_dict[key]["prompt"] += p
                bucket_dict[key]["thinking"] += th
                bucket_dict[key]["candidates"] += c
                bucket_dict[key]["total"] += (p + th + c)
                bucket_dict[key]["count"] += 1

        buckets = list(bucket_dict.values())

    # 6. SESSION TIMELINE (Step by step / Turn by turn)
    elif timeframe_norm in ("session", "timeline", "turns"):
        if not valid_records:
            return []
        
        total_steps = len(valid_records)
        chunk_size = max(1, total_steps // 30)

        step_idx = 1
        for i in range(0, total_steps, chunk_size):
            chunk = valid_records[i : i + chunk_size]
            p_sum = sum(x[1] for x in chunk)
            th_sum = sum(x[2] for x in chunk)
            c_sum = sum(x[3] for x in chunk)
            first_dt = chunk[0][0]
            
            if chunk_size == 1:
                lbl = f"T{step_idx}"
                full_lbl = f"Turn {step_idx} ({first_dt.strftime('%H:%M:%S')})"
            else:
                end_step = min(total_steps, i + chunk_size)
                lbl = f"T{i+1}-{end_step}"
                full_lbl = f"Turns {i+1} to {end_step}"

            buckets.append({
                "key": f"step_{step_idx}",
                "label": lbl,
                "full_label": full_lbl,
                "dt": first_dt,
                "prompt": p_sum,
                "thinking": th_sum,
                "candidates": c_sum,
                "total": p_sum + th_sum + c_sum,
                "count": len(chunk),
            })
            step_idx += 1

    # 7. ALL-TIME / LIFETIME TIMEFRAME
    elif timeframe_norm in ("all", "all_time", "lifetime"):
        if not valid_records:
            return []
        min_dt = valid_records[0][0]
        max_dt = valid_records[-1][0]
        span_days = max(1, (max_dt.date() - min_dt.date()).days + 1)
        if span_days <= 31:
            bucket_dict = {}
            for i in range(span_days):
                b_dt = (min_dt + timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
                key = b_dt.strftime("%Y-%m-%d")
                lbl = b_dt.strftime("%b %d")
                bucket_dict[key] = {
                    "key": key,
                    "label": lbl,
                    "full_label": b_dt.strftime("%A, %b %d, %Y"),
                    "dt": b_dt,
                    "prompt": 0,
                    "thinking": 0,
                    "candidates": 0,
                    "total": 0,
                    "count": 0,
                }
            for dt, p, th, c in valid_records:
                key = dt.strftime("%Y-%m-%d")
                if key in bucket_dict:
                    bucket_dict[key]["prompt"] += p
                    bucket_dict[key]["thinking"] += th
                    bucket_dict[key]["candidates"] += c
                    bucket_dict[key]["total"] += (p + th + c)
                    bucket_dict[key]["count"] += 1
            buckets = list(bucket_dict.values())
        else:
            years_months = []
            cur_y, cur_m = min_dt.year, min_dt.month
            end_y, end_m = max_dt.year, max_dt.month
            while (cur_y < end_y) or (cur_y == end_y and cur_m <= end_m):
                years_months.append((cur_y, cur_m))
                cur_m += 1
                if cur_m > 12:
                    cur_m = 1
                    cur_y += 1
            bucket_dict = {}
            for y, m in years_months:
                dt_m = datetime(y, m, 1, tzinfo=now.tzinfo)
                key = dt_m.strftime("%Y-%m")
                lbl = dt_m.strftime("%b %y")
                bucket_dict[key] = {
                    "key": key,
                    "label": lbl,
                    "full_label": dt_m.strftime("%B %Y"),
                    "dt": dt_m,
                    "prompt": 0,
                    "thinking": 0,
                    "candidates": 0,
                    "total": 0,
                    "count": 0,
                }
            for dt, p, th, c in valid_records:
                key = dt.strftime("%Y-%m")
                if key in bucket_dict:
                    bucket_dict[key]["prompt"] += p
                    bucket_dict[key]["thinking"] += th
                    bucket_dict[key]["candidates"] += c
                    bucket_dict[key]["total"] += (p + th + c)
                    bucket_dict[key]["count"] += 1
            buckets = list(bucket_dict.values())

    return buckets


def calculate_analytics_summary(buckets: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculates summary statistics across aggregated buckets."""
    total_prompt = sum(b.get("prompt", 0) for b in buckets)
    total_thinking = sum(b.get("thinking", 0) for b in buckets)
    total_candidates = sum(b.get("candidates", 0) for b in buckets)
    grand_total = total_prompt + total_thinking + total_candidates

    prompt_pct = (total_prompt / grand_total * 100) if grand_total > 0 else 0.0
    thinking_pct = (total_thinking / grand_total * 100) if grand_total > 0 else 0.0
    candidates_pct = (total_candidates / grand_total * 100) if grand_total > 0 else 0.0

    active_buckets = [b for b in buckets if b.get("total", 0) > 0]
    peak_bucket = max(buckets, key=lambda b: b.get("total", 0)) if buckets else None
    avg_per_active = (grand_total / len(active_buckets)) if active_buckets else 0.0
    avg_per_total = (grand_total / len(buckets)) if buckets else 0.0

    return {
        "total_tokens": grand_total,
        "prompt_tokens": total_prompt,
        "thinking_tokens": total_thinking,
        "candidates_tokens": total_candidates,
        "prompt_pct": round(prompt_pct, 2),
        "thinking_pct": round(thinking_pct, 2),
        "candidates_pct": round(candidates_pct, 2),
        "peak_bucket": peak_bucket,
        "peak_tokens": peak_bucket.get("total", 0) if peak_bucket else 0,
        "peak_label": peak_bucket.get("full_label", "N/A") if peak_bucket else "N/A",
        "avg_tokens_per_bucket": round(avg_per_total, 1),
        "avg_tokens_active_bucket": round(avg_per_active, 1),
        "active_buckets_count": len(active_buckets),
        "total_buckets_count": len(buckets),
    }


def generate_ascii_chart(buckets: List[Dict[str, Any]], title: str = "Gemini Token Usage Chart", max_bar_width: int = 36) -> str:
    """Generates an attractive ASCII/Unicode horizontal bar chart for terminal display."""
    if not buckets:
        return f"\n=== {title} ===\nNo usage data available for this timeframe.\n"

    summary = calculate_analytics_summary(buckets)
    max_val = max(b.get("total", 0) for b in buckets)
    if max_val <= 0:
        max_val = 1

    lines = []
    lines.append("=" * 64)
    lines.append(f"  {title.upper()}  ".center(64))
    lines.append("=" * 64)
    lines.append(f"  ★ Period Total Tokens:    {summary['total_tokens']:>16,}")
    lines.append(f"  📥 Prompt (Input):        {summary['prompt_tokens']:>16,} ({summary['prompt_pct']}%)")
    lines.append(f"  🧠 Thinking (Reasoning):  {summary['thinking_tokens']:>16,} ({summary['thinking_pct']}%)")
    lines.append(f"  📤 Output (Candidate):    {summary['candidates_tokens']:>16,} ({summary['candidates_pct']}%)")
    if summary["peak_tokens"] > 0:
        lines.append(f"  ⚡ Peak Interval:          {summary['peak_label']} ({summary['peak_tokens']:,} tokens)")
    lines.append("-" * 64)
    lines.append("  [Legend: █ Prompt | ▓ Thinking | ░ Output]")
    lines.append("-" * 64)

    # Render each bucket bar
    for b in buckets:
        lbl = b.get("label", "")
        tot = b.get("total", 0)
        p = b.get("prompt", 0)
        th = b.get("thinking", 0)

        # Scale bar width
        bar_len = int((tot / max_val) * max_bar_width) if max_val > 0 else 0
        if tot > 0 and bar_len == 0:
            bar_len = 1

        if tot > 0:
            p_len = int((p / tot) * bar_len)
            th_len = int((th / tot) * bar_len)
            c_len = max(0, bar_len - (p_len + th_len))
            bar_str = ("█" * p_len) + ("▓" * th_len) + ("░" * c_len)
        else:
            bar_str = "·"

        val_str = f"{tot:,}" if tot > 0 else "-"
        lines.append(f"  {lbl:>8} │ {bar_str:<{max_bar_width}} {val_str:>10}")

    lines.append("=" * 64)
    return "\n".join(lines)


def export_analytics_csv(buckets: List[Dict[str, Any]], filepath: str):
    """Exports usage time-series buckets to CSV."""
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Timestamp / Bucket", "Prompt (Input)", "Thinking (Reasoning)", "Output (Candidates)", "Total Tokens", "Interactions Count"])
        for b in buckets:
            writer.writerow([
                b.get("full_label") or b.get("key"),
                b.get("prompt", 0),
                b.get("thinking", 0),
                b.get("candidates", 0),
                b.get("total", 0),
                b.get("count", 0),
            ])


def export_analytics_json(buckets: List[Dict[str, Any]], summary: Dict[str, Any], filepath: str):
    """Exports usage time-series buckets and summary to JSON."""
    data = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "buckets": [
            {
                "key": b.get("key"),
                "label": b.get("label"),
                "full_label": b.get("full_label"),
                "prompt_tokens": b.get("prompt", 0),
                "thinking_tokens": b.get("thinking", 0),
                "candidates_tokens": b.get("candidates", 0),
                "total_tokens": b.get("total", 0),
                "interactions_count": b.get("count", 0),
            }
            for b in buckets
        ]
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
