#!/usr/bin/env python3
import os
import sys
import argparse

# Add directory to sys.path
root_dir = os.path.dirname(os.path.abspath(__file__))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

# Ensure proper UTF-8 output formatting
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import json
import time
from core.session_finder import get_all_session_files
from core.engine import get_single_session_report, get_all_sessions_report, get_active_account_report
from core.account_manager import get_active_google_account
from core.ledger import ledger
from core.analytics import bucket_records_by_time, calculate_analytics_summary, generate_ascii_chart
from core.cleaner import (
    get_disk_usage_summary,
    delete_session_files,
    prune_sessions_by_age,
    prune_sessions_keep_latest,
    prune_empty_sessions,
    prune_all_previous,
    paginate_items,
)


def report_current_session(specific_id: str = None, as_json: bool = False):
    sessions = get_all_session_files()
    if not sessions:
        if as_json:
            print(json.dumps({"error": "No active sessions found"}))
        else:
            print("\nNo active sessions or transcripts found.\n")
        return

    target_session = None
    if specific_id:
        for s in sessions:
            if specific_id.lower() in s["session_id"].lower():
                target_session = s
                break
        if not target_session:
            if as_json:
                print(json.dumps({"error": f"Session ID '{specific_id}' not found"}))
            else:
                print(f"\nSession ID '{specific_id}' not found.\n")
            return
    else:
        target_session = sessions[0]

    active_email = get_active_google_account() or "Default"
    report = get_single_session_report(target_session, account_email=active_email)
    acc_report = get_active_account_report(active_email, sessions=sessions)

    if as_json:
        if specific_id:
            print(json.dumps(report, indent=2, default=str))
        else:
            print(json.dumps({
                "account_report": acc_report,
                "active_chat_report": report
            }, indent=2, default=str))
        return

    prompt_title = report.get("first_prompt") or report.get("title", "")

    if specific_id:
        print("\n" + "=" * 62)
        print("             GEMINI SESSION TOKEN REPORT                ")
        print("=" * 62)
        if active_email and active_email != "Default":
            print(f"  👤 Account:                 {active_email}")
        print(f"  ⚡ Session ID:               {report['session_id']}")
        if prompt_title and prompt_title != report['session_id']:
            print(f"  💬 Topic:                   {prompt_title[:45]}")
        print(f"  🕒 Last Active:             {report['last_active']}")
        print("-" * 62)
        print(f"  • Prompt (Input) Tokens:    {report['prompt']:>16,}")
        print(f"  • Thinking / Planning:      {report['thinking']:>16,}")
        print(f"  • Candidate (Output) Tokens:{report['candidates']:>16,}")
        print("-" * 62)
        print(f"  ★ SESSION TOTAL:            {report['total']:>16,}")
        print("=" * 62)
        print("           ROLLING QUOTA BURN RATE (THIS SESSION)         ")
        print("-" * 62)
        print(f"  ⚡ Instant Burn Velocity:    {report.get('burn_rate_str', 'Idle'):>16}")
        print(f"  ⏳ Last 5-Hours Burn Rate:   {report['tokens_5h']:>16,} tokens")
        print(f"  🔄 5-Hour Window Recovery:  {report['reset_5h_str']:>32}")
        print(f"  📅 Last 7-Days Total:       {report['tokens_7d']:>16,} tokens")
        print(f"  🗓️ Weekly Window Recovery:  {report['reset_7d_str']:>32}")
        print("=" * 62 + "\n")
    else:
        print("\n" + "=" * 62)
        print("             ACTIVE CONVERSATION TOKEN REPORT             ")
        print("=" * 62)
        print(f"  ⚡ Active Session ID:        {report['session_id']}")
        if prompt_title and prompt_title != report['session_id']:
            print(f"  💬 Topic:                   {prompt_title[:45]}")
        print(f"  🕒 Last Active:             {report['last_active']}")
        if active_email and active_email != "Default":
            print(f"  👤 Associated Account:      {active_email}")
        print("-" * 62)
        print("  ACTIVE CONVERSATION BREAKDOWN:")
        print(f"  • Prompt (Input) Tokens:    {report['prompt']:>16,}")
        print(f"  • Thinking / Planning:      {report['thinking']:>16,}")
        print(f"  • Candidate (Output) Tokens:{report['candidates']:>16,}")
        print("-" * 62)
        print(f"  ★ ACTIVE SESSION TOTAL:     {report['total']:>16,}")
        print("=" * 62)
        print("       GOOGLE ACCOUNT & ROLLING LIMITS (ALL LOGS)         ")
        print("-" * 62)
        if active_email and active_email != "Default":
            print(f"  👤 Account Email:           {active_email}")
            print(f"  📁 Account Chats Tracked:   {acc_report.get('unique_sessions_count', 1):>16,}")
        print(f"  ★ Account Lifetime Total:   {acc_report['total']:>16,} tokens")
        print(f"  ⚡ Instant Burn Velocity:    {acc_report.get('burn_rate_str', 'Idle'):>16}")
        print(f"  ⏳ Last 5-Hours User Burn:   {acc_report['tokens_5h']:>16,} tokens")
        print(f"  🔄 5-Hour Window Recovery:  {acc_report['reset_5h_str']:>32}")
        print(f"  📅 Last 7-Days User Total:  {acc_report['tokens_7d']:>16,} tokens")
        print(f"  🗓️ Weekly Window Recovery:  {acc_report['reset_7d_str']:>32}")
        print("=" * 62)
        print("  [Tip] Run with --graph for usage charts, or --all for device total.\n")


def report_account_sessions(account_email: str = None, as_json: bool = False):
    sessions = get_all_session_files()
    active_email = account_email or get_active_google_account() or "Default"
    report = get_active_account_report(active_email, sessions=sessions)

    if as_json:
        print(json.dumps(report, indent=2, default=str))
        return

    print("\n" + "=" * 62)
    print(f"     ACCOUNT ROLLING QUOTA REPORT ({active_email[:25]})     ")
    print("=" * 62)
    print(f"  Google Account:             {active_email}")
    print(f"  Account Chats Tracked:      {report.get('unique_sessions_count', 0):>16,}")
    print("-" * 62)
    print(f"  • Prompt (Input) Tokens:    {report['prompt']:>16,}")
    print(f"  • Thinking / Planning:      {report['thinking']:>16,}")
    print(f"  • Candidate (Output) Tokens:{report['candidates']:>16,}")
    print("-" * 62)
    print(f"  ★ ACCOUNT GRAND TOTAL:      {report['total']:>16,}")
    print("=" * 62)
    print("      ROLLING ACCOUNT QUOTA (MATCHES GOOGLE LIMITS)       ")
    print("-" * 62)
    print(f"  ⚡ Instant Burn Velocity:    {report.get('burn_rate_str', 'Idle'):>16}")
    print(f"  ⏳ Last 5 Hours (Account):   {report['tokens_5h']:>16,} tokens")
    print(f"  🔄 5-Hour Window Recovery:  {report['reset_5h_str']:>32}")
    print(f"  📅 Last 7 Days (Account):   {report['tokens_7d']:>16,} tokens")
    print(f"  🗓️ Weekly Window Recovery:  {report['reset_7d_str']:>32}")
    print("=" * 62 + "\n")


def report_all_sessions(as_json: bool = False):
    sessions = get_all_session_files()
    if not sessions:
        if as_json:
            print(json.dumps({"error": "No transcripts found"}))
        else:
            print("\nNo transcripts found.\n")
        return

    report = get_all_sessions_report(sessions)

    if as_json:
        print(json.dumps(report, indent=2, default=str))
        return

    print("\n" + "=" * 62)
    print("      GEMINI TOTAL TOKEN CONSUMPTION (ALL ACCOUNTS)       ")
    print("=" * 62)
    print(f"  Unique Sessions Tracked:    {report['unique_sessions_count']:>16,}")
    print("-" * 62)
    print(f"  • Prompt (Input) Tokens:    {report['prompt']:>16,}")
    print(f"  • Thinking / Planning:      {report['thinking']:>16,}")
    print(f"  • Candidate (Output) Tokens:{report['candidates']:>16,}")
    print("-" * 62)
    print(f"  ★ DEVICE GRAND TOTAL:       {report['total']:>16,}")
    print("=" * 62)
    print("     CUMULATIVE DEVICE CONSUMPTION (ALL CHATS & USERS)    ")
    print("-" * 62)
    print(f"  ⚡ Instant Burn Velocity:    {report.get('burn_rate_str', 'Idle'):>16}")
    print(f"  ⏳ Last 5 Hours (All Chats): {report['tokens_5h']:>16,} tokens")
    print(f"  🔄 5-Hour Window Recovery:  {report['reset_5h_str']:>32}")
    print(f"  📅 Last 7 Days (All Chats): {report['tokens_7d']:>16,} tokens")
    print(f"  🗓️ Weekly Window Recovery:  {report['reset_7d_str']:>32}")
    print("=" * 62)
    print("  [Note] Rolling quotas are per-account; run with --account for account quota.\n")


def report_usage_graph(timeframe: str = "7d", specific_id: str = None, account_mode: bool = False, as_json: bool = False):
    """Renders an ASCII usage graph in terminal or returns JSON time buckets."""
    # Ensure ledger is synced
    get_all_sessions_report(get_all_session_files())

    active_email = get_active_google_account() or "Default"
    if specific_id:
        records = ledger.get_all_time_series_records(session_id=specific_id)
        title = f"Usage Chart: Session {specific_id[:16]} ({timeframe.upper()})"
    elif account_mode:
        records = ledger.get_all_time_series_records(account_email=active_email)
        title = f"Usage Chart: Account {active_email} ({timeframe.upper()})"
    else:
        records = ledger.get_all_time_series_records()
        title = f"Usage Chart: All Sessions ({timeframe.upper()})"

    buckets = bucket_records_by_time(records, timeframe=timeframe)
    summary = calculate_analytics_summary(buckets)

    if as_json:
        payload = {"title": title, "timeframe": timeframe, "summary": summary, "buckets": buckets}
        print(json.dumps(payload, indent=2, default=str))
    else:
        print("\n" + generate_ascii_chart(buckets, title=title) + "\n")


def report_disk_usage(page: int = 1, limit: int = 10, as_json: bool = False):
    """Prints storage summary and paginated per-session disk usage breakdown."""
    summary = get_disk_usage_summary()
    all_sessions = summary.get("sessions", [])
    paginated = paginate_items(all_sessions, page=page, page_size=limit)

    if as_json:
        payload = {
            "total_sessions": summary["total_sessions"],
            "total_bytes": summary["total_bytes"],
            "total_size_str": summary["total_size_str"],
            "pagination": {
                "page": paginated["page"],
                "limit": paginated["page_size"],
                "total_pages": paginated["total_pages"],
                "total_count": paginated["total_count"],
                "has_next": paginated["has_next"],
                "has_prev": paginated["has_prev"],
                "start_idx": paginated["start_idx"],
                "end_idx": paginated["end_idx"],
            },
            "sessions": paginated["items"],
        }
        print(json.dumps(payload, indent=2, default=str))
        return

    print("\n" + "=" * 62)
    print("           GEMINI SESSION STORAGE & DISK USAGE            ")
    print("=" * 62)
    print(f"  Total Sessions Found:       {summary['total_sessions']:>16,}")
    print(f"  Total Storage Consumed:     {summary['total_size_str']:>16}")
    print("-" * 62)
    if summary["total_sessions"] == 0:
        print("  No session transcripts found on disk.")
    else:
        start_idx = paginated["start_idx"]
        end_idx = paginated["end_idx"]
        tot_cnt = paginated["total_count"]
        print(f"  Showing page {paginated['page']} of {paginated['total_pages']} ({paginated['page_size']} items per page, sessions {start_idx}-{end_idx} of {tot_cnt}):")
        for s in paginated["items"]:
            sid = s["session_id"]
            short_id = sid if len(sid) <= 24 else f"{sid[:12]}...{sid[-8:]}"
            print(f"  • {short_id:<26}  {s['size_str']:>9}  ({s['last_active'][:10]})")
    print("-" * 62)
    print("  Use --page <N> and --limit <N> to view other session pages.")
    print("=" * 62)
    print("  [Tip] Use --clean-older-than <DAYS> or --keep-latest <N> to free disk space.\n")


def handle_cleaning(
    older_than: int = None,
    keep_latest: int = None,
    delete_session: str = None,
    clean_empty: bool = False,
    clean_all_prev: bool = False
):
    """Executes session pruning commands from CLI."""
    if delete_session:
        _, _, msg = delete_session_files(delete_session)
        print(f"\n[CLEAN] {msg}\n")
    elif older_than is not None:
        res = prune_sessions_by_age(older_than, keep_active=True)
        print(f"\n[CLEAN] Pruned {res['deleted_count']} session(s) older than {older_than} days. Freed {res['freed_str']}.\n")
    elif keep_latest is not None:
        res = prune_sessions_keep_latest(keep_latest, keep_active=True)
        print(f"\n[CLEAN] Kept latest {keep_latest} sessions, pruned {res['deleted_count']} older session(s). Freed {res['freed_str']}.\n")
    elif clean_empty:
        res = prune_empty_sessions()
        print(f"\n[CLEAN] Removed {res['deleted_count']} empty / 0-token session(s). Freed {res['freed_str']}.\n")
    elif clean_all_prev:
        res = prune_all_previous(keep_active=True)
        print(f"\n[CLEAN] Deleted {res['deleted_count']} historical session(s) (preserved active session). Freed {res['freed_str']}.\n")


def watch_loop(specific_id: str = None, all_mode: bool = False, account_mode: bool = False, interval: int = 3):
    """Runs a live refreshing terminal monitor loop."""
    try:
        while True:
            os.system("cls" if os.name == "nt" else "clear")
            if account_mode:
                report_account_sessions(as_json=False)
            elif all_mode:
                report_all_sessions(as_json=False)
            else:
                report_current_session(specific_id=specific_id, as_json=False)
            print(f"  [Live Watch Mode] Refreshing every {interval}s... Press Ctrl+C to exit.")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nExiting watch mode.")


def main():
    parser = argparse.ArgumentParser(description="Track, report, graph, and compact Gemini token consumption.")
    parser.add_argument("--account", "-u", nargs="?", const="ACTIVE", default=None, help="Report rolling quota for the active Google Account or specified email")
    parser.add_argument("--all", "-a", action="store_true", help="Report cumulative tokens across all sessions/accounts")
    parser.add_argument("--session", "-s", type=str, default=None, help="Report tokens for a specific session ID")
    parser.add_argument("--gui", "-g", action="store_true", help="Launch the Desktop GUI monitor")
    parser.add_argument("--json", "-j", action="store_true", help="Output machine-readable JSON format")
    parser.add_argument("--watch", "-w", action="store_true", help="Continuously monitor in terminal with live refresh")
    parser.add_argument("--interval", "-i", type=int, default=3, help="Polling interval in seconds for --watch mode")
    parser.add_argument("--page", "-p", type=int, default=1, help="Page number for paginated session listings (default: 1)")
    parser.add_argument("--limit", "-l", type=int, default=10, help="Maximum number of items per page (default: 10)")

    # Usage Graphs & Analytics
    parser.add_argument("--graph", action="store_true", help="Render ASCII usage chart in terminal")
    parser.add_argument("--history", type=str, nargs="?", const="5h", choices=["5h", "24h", "7d", "30d", "month", "year", "session"], help="View usage history chart for specified timeframe (default: 5h)")

    # Storage Cleaner & Compactor
    parser.add_argument("--disk-usage", action="store_true", help="Display storage consumption by session transcripts")
    parser.add_argument("--clean-older-than", type=int, metavar="DAYS", help="Prune sessions older than specified number of days")
    parser.add_argument("--keep-latest", type=int, metavar="N", help="Keep only the latest N sessions and prune older ones")
    parser.add_argument("--delete-session", type=str, metavar="SESSION_ID", help="Permanently delete a specific session to free space")
    parser.add_argument("--clean-empty", action="store_true", help="Remove empty or 0-token session transcripts")
    parser.add_argument("--clean-previous", action="store_true", help="Delete all previous sessions, preserving only the active one")

    args = parser.parse_args()

    if args.gui:
        from gui.app import GeminiTokenCounterApp
        app = GeminiTokenCounterApp()
        app.mainloop()
    elif args.disk_usage:
        report_disk_usage(page=args.page, limit=args.limit, as_json=args.json)
    elif args.clean_older_than is not None or args.keep_latest is not None or args.delete_session or args.clean_empty or args.clean_previous:
        handle_cleaning(
            older_than=args.clean_older_than,
            keep_latest=args.keep_latest,
            delete_session=args.delete_session,
            clean_empty=args.clean_empty,
            clean_all_prev=args.clean_previous
        )
    elif args.graph or args.history:
        tf = args.history if args.history else "5h"
        report_usage_graph(timeframe=tf, specific_id=args.session, account_mode=bool(args.account), as_json=args.json)
    elif args.watch:
        watch_loop(specific_id=args.session, all_mode=args.all, account_mode=bool(args.account), interval=args.interval)
    elif args.account:
        target_email = None if args.account == "ACTIVE" else args.account
        report_account_sessions(account_email=target_email, as_json=args.json)
    elif args.all:
        report_all_sessions(as_json=args.json)
    else:
        report_current_session(specific_id=args.session, as_json=args.json)


if __name__ == "__main__":
    main()
