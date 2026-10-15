"""Import a CG group into an isolated preview or existing main catalog, offline."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio import cg_sequence


def main():
    parser=argparse.ArgumentParser(description='只生成CG差分缓存；不修改存档或自动审核')
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--group',default='ev_shi_c04')
    args=parser.parse_args()
    item=cg_sequence.build(args.root,args.group);doc=cg_sequence.load(args.root,item)
    print('CG组:',doc['group'],'完整画面:',len(doc['frames']),'脚本步骤:',len(doc['steps']))
    print('输出:',args.root/item['relative_path'])
    print('仅差分合成和手动切换；不是原作完整动画；未写入正式存档或审核记录。')


if __name__=='__main__':main()
