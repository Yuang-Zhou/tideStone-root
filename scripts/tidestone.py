#!/usr/bin/env python3
"""潮石本地研究入口。只管理真实材料、草稿、审阅和历史，不生成研究结论。"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'Projects'/'_system'/'scripts'))
import local_workflow as local


def parser():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('init',help='初始化空库；已有文件不覆盖')
    a=sub.add_parser('add',help='登记公司，生成空档案目录')
    a.add_argument('ticker');a.add_argument('--name',required=True)
    a.add_argument('--market',required=True,choices=['US','HK','CN','OTHER'])
    a.add_argument('--sector',default='unknown',help='GICS 一级代码；未核实则 unknown')
    a.add_argument('--currency',help='三位大写报价币种；US/HK/CN 默认 USD/HKD/CNY，OTHER 必填')
    a=sub.add_parser('track',help='启用/暂停公司日常跟踪；模拟盘另须通过数据和策略条件')
    a.add_argument('ticker');a.add_argument('--status',required=True,choices=['active','paused'])
    a.add_argument('--reason',required=True)
    a=sub.add_parser('material',help='复制并登记实际材料及来源哈希')
    a.add_argument('ticker');a.add_argument('--file',required=True);a.add_argument('--source',required=True)
    a.add_argument('--kind',required=True);a.add_argument('--period',default='')
    a=sub.add_parser('prepare',help='准备研究批次，真实分析由 Codex Skills 写入')
    a.add_argument('ticker');a.add_argument('--slots',nargs='+');a.add_argument('--trigger',default='manual')
    a=sub.add_parser('finalize',help='校验真实模块并生成待审差异')
    a.add_argument('ticker');a.add_argument('timestamp')
    for name in ['revise','accept','reject']:
        a=sub.add_parser(name)
        a.add_argument('ticker');a.add_argument('timestamp');a.add_argument('--reason',required=True)
    a=sub.add_parser('event',help='保存新财报/事件/预测偏差及受影响模块')
    a.add_argument('ticker');a.add_argument('--title',required=True);a.add_argument('--source',required=True)
    a.add_argument('--detail',default='');a.add_argument('--slots',nargs='+')
    a=sub.add_parser('status',help='重扫磁盘并读取跨会话工作状态')
    a.add_argument('ticker',nargs='?');a.add_argument('--json',action='store_true')
    a=sub.add_parser('sync',help='将已接受07登记块同步到估值注册表；缺失则留待处理')
    a.add_argument('ticker',nargs='?')
    return p


def main(argv=None):
    a=parser().parse_args(argv)
    try:
        with local.lock():
            local.init()
            if a.command=='init':result=local.init()
            else:
                if hasattr(a,'ticker') and a.ticker:a.ticker=local.checked_ticker(a.ticker)
                if a.command=='add':
                    result=local.add(a.ticker,a.name,a.market,a.sector,a.currency)
                elif a.command=='track':
                    result=local.track(a.ticker,a.status,a.reason)
                elif a.command=='material':
                    result=local.material(a.ticker,a.file,a.source,a.kind,a.period)
                elif a.command=='event':
                    result=local.event(a.ticker,a.title,a.source,a.detail,a.slots)
                elif a.command=='revise':
                    result=local.revise(a.ticker,a.timestamp,a.reason)
                else:
                    import dossier_orchestrator as engine
                    if a.command=='prepare':result=local.prepare(engine,a.ticker,a.slots,a.trigger)
                    elif a.command=='finalize':
                        result=local.finalize(engine,a.ticker,a.timestamp)
                    elif a.command=='accept':result=local.accept(engine,a.ticker,a.timestamp,a.reason)
                    elif a.command=='reject':result=local.reject(engine,a.ticker,a.timestamp,a.reason)
                    elif a.command=='status':result=local.status(engine,a.ticker)
                    elif a.command=='sync':
                        import sync_valuations
                        sync_valuations.cmd_drain([a.ticker] if a.ticker else None)
                        queue=local.read(local.SYSTEM/'pending_valuation_sync.json',{'pending':[]})['pending']
                        result={'pending':[x for x in queue if not a.ticker or x['ticker']==a.ticker]}
                if a.command=='add':
                    import dossier_orchestrator as engine
                    engine.rescan_one(a.ticker)
            print(json.dumps(result,ensure_ascii=False,indent=2))
            if a.command=='finalize' and result['batch_status']!='ready_for_review':return 1
            if a.command=='sync' and result['pending']:return 1
        return 0
    except (ValueError,OSError,KeyError,json.JSONDecodeError) as exc:
        print('无法完成：'+str(exc),file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
