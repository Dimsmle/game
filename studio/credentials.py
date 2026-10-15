"""Private, backend-only API credentials. Never merge into public settings."""
import json
import os
from pathlib import Path
import sys

ALLOWED={'DEEPSEEK_API_KEY','LLM_API_KEY','IMAGE_API_KEY'}


def secrets_path():
    if getattr(sys,'frozen',False):
        return Path(os.getenv('LOCALAPPDATA') or Path.home())/'CharacterLab'/'local_secrets.json'
    return Path(__file__).resolve().parents[1]/'local_secrets.json'


def _validate(value):
    if not isinstance(value,str) or len(value)>4096:raise ValueError('密钥必须为不超过 4096 字的字符串')
    value=value.strip()
    if not value.isascii() or any(ord(char)<=32 or ord(char)==127 for char in value):raise ValueError('密钥包含非 ASCII、空白或控制字符')
    return value


def _object(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('重复字段')
        result[key]=value
    return result


def read_file(path=None):
    path=Path(path) if path is not None else secrets_path()
    try:
        if not path.exists():return {}
        if path.stat().st_size>16384:raise ValueError('文件过大')
        data=json.loads(path.read_text(encoding='utf-8-sig'),object_pairs_hook=_object)
        if not isinstance(data,dict) or set(data)-ALLOWED:raise ValueError('字段无效')
        return {key:_validate(value) for key,value in data.items()}
    except (OSError,ValueError,UnicodeError,RecursionError):
        # JSONDecodeError can embed secret text in its diagnostic. Never return it.
        raise RuntimeError('本机 local_secrets.json 无效；请检查 JSON 格式、字段名和密钥字符串') from None


def get_api_key(name):
    if name not in ALLOWED:raise ValueError('不支持的密钥名称')
    value=os.getenv(name,'')
    if value:
        try:return _validate(value)
        except ValueError:raise RuntimeError('API 密钥环境变量格式无效') from None
    return read_file().get(name,'')


def status(name='DEEPSEEK_API_KEY'):
    try:
        present=bool(get_api_key(name))
        return {'present':present,'source':('environment' if os.getenv(name) else 'local_file') if present else 'missing'}
    except RuntimeError as error:
        return {'present':False,'source':'invalid','error':str(error)}
