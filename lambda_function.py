import json
import hmac, hashlib
import boto3
import base64
import ast, re
import os
from botocore.exceptions import ClientError

def lambda_handler(event, context):

    body = event['body']
    if is_correct_signature(event['headers']['x-hub-signature'], body):
        print('認証成功')
    project_names = []
    job_name_suffix = os.environ['job_name_suffix']
    body_json = json.loads(body)
    ref = body_json['ref']
    if ref == os.environ['trigger_branch'] and len(body_json['commits']) > 0:
        # 指定ブランチへのコミットの場合だけ処理
        added_files = body_json['commits'][0]['added']
        removed_files = body_json['commits'][0]['removed']
        modified_files = body_json['commits'][0]['modified'] + added_files + removed_files
        print('added / removed / modified : {}'.format(modified_files))
        # どのプロジェクトのビルドを行うかファイルパスから判断
        includes = ['project1', 'project2', 'project3']
        pipelines_count_max = len(includes)
        common = ['common']
        for file_path in modified_files:
            pos = file_path.find('/')
            if pos > 0:
                # パスにフォルダを含む→プロジェクト名を確認
                project_name = file_path[:pos]
                if common.count(project_name) > 0:
                    # 共有プロジェクト名であれば全て呼び出しパイプラインに含める
                    project_names = includes
                    break
                if project_names.count(project_name) == 0:
                    # 対象プロジェクト初検出→呼び出しパイプラインに含める
                        project_names.append(project_name)
                        if len(project_names) == pipelines_count_max:
                            # すべてのプロジェクトを検出→ループを抜ける
                            break
        # 対象プロジェクトをビルドするパイプラインを呼び出す
        print('projects : {}'.format(project_names))
        if len(project_names) > 0:
            for project_name in project_names:
                return_code = start_code_pipeline('{}{}'.format(project_name, job_name_suffix))
                print(return_code)

    return {
        'statusCode': 200,
        'body': json.dumps('Modified project in repo: {}'.format(project_names))
    }
    
def get_secrets_manager_dict(secret_name: str) -> dict:
    """Secrets Managerからシークレットのセットを辞書型で取得する"""
    secrets_dict = {}
    if not secret_name:
        print('シークレットの名前未設定')
    else:
        session = boto3.session.Session()
        client = session.client(
            service_name='secretsmanager',
            region_name='ap-northeast-1'
        )
        try:
            get_secret_value_response = client.get_secret_value(
                SecretId=secret_name
            )
        except ClientError as e:
            print('シークレット取得失敗：シークレットの名前={}'.format(secret_name))
            print(e.response['Error'])
        else:
            if 'SecretString' in get_secret_value_response:
                secret = get_secret_value_response['SecretString']
            else:
                secret = base64.b64decode(get_secret_value_response['SecretBinary'])
            secrets_dict = ast.literal_eval(secret)
    return secrets_dict

def get_secrets_manager_key_value(secret_name: str, secret_key: str) -> str:
    """AWS Secrets Managerからシークレットキーの値を取得する."""
    value = ''
    secrets_dict = get_secrets_manager_dict(secret_name)
    if secrets_dict:
        if secret_key in secrets_dict:
            # secrets_dictが設定されていてsecret_keyがキーとして存在する場合
            value = secrets_dict[secret_key]
        else:
            print('シークレットキーの値取得失敗：シークレットの名前={}、シークレットキー={}'.format(secret_name, secret_key))
    return value

def is_correct_signature(signature: str, body: dict) -> bool:
    """GitHubから送られてきた情報をHMAC認証する."""
    if signature and body:
        # GitHubのWebhookに設定したSecretをSecrets Managerから取得する
        secret = get_secrets_manager_key_value(os.environ['secrets_name'], 'GHE_SECRETS')
        if secret:
            secret_bytes = bytes(secret, 'utf-8')
            body_bytes = bytes(body, 'utf-8')
            # Secretから16進数ダイジェストを作成する
            signedBody = "sha1=" + hmac.new(secret_bytes, body_bytes, hashlib.sha1).hexdigest()
            return signature == signedBody
    else:
        return False

def start_code_pipeline(pipelineName):
    client = codepipeline_client()
    response = client.start_pipeline_execution(name=pipelineName)
    return True

cpclient = None
def codepipeline_client():
    global cpclient
    if not cpclient:
        cpclient = boto3.client('codepipeline')
    return cpclient
