"""Terminal rendering only; coverage policy is shared by analytics/API/reports."""

from ..analytics.coverage import coverage_lines


def print_coverage(report):
    print("数据覆盖（描述输入完整性，不是命令执行状态）：")
    for line in coverage_lines(report):
        print("  " + line)
