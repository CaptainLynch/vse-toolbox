import json

with open(r'E:\project\vse-toolbox\crawl source\ecm.sgmw.com.cn-EWO.har', 'r', encoding='utf-8') as f:
    har_data = json.load(f)

for entry in har_data['log']['entries']:
    req = entry['request']
    if 'InnovatorServer.aspx' in req['url'] and req['method'] == 'POST':
        post_data = req.get('postData', {}).get('text', '')
        if 'EWO_O' in post_data:
            print('Headers:')
            for h in req['headers']:
                if h['name'].lower() in ['authorization', 'cookie', 'soapaction', 'content-type', 'authuser']:
                    val = h['value']
                    if len(val) > 100: val = val[:100] + '...'
                    print(f"{h['name']}: {val}")
            break
