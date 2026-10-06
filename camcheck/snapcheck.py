#!/usr/bin/python3
"""Is a GNOME Snapshot video stream running in PipeWire? Prints the camera it reads."""
import json
import subprocess
import sys

d = json.loads(subprocess.run(['pw-dump'], capture_output=True, text=True).stdout)
nodes = {o['id']: o for o in d if o.get('type') == 'PipeWire:Interface:Node'}
for o in nodes.values():
    p = o.get('info', {}).get('props', {})
    if p.get('media.class') == 'Stream/Input/Video' and 'napshot' in (p.get('application.name', '') + p.get('application.id', '') + p.get('node.name', '')):
        state = o['info'].get('state')
        src = [nodes.get(lk['info']['output-node-id'], {}).get('info', {}).get('props', {}).get('node.name')
               for lk in d if lk.get('type') == 'PipeWire:Interface:Link' and lk['info']['input-node-id'] == o['id']]
        print(f'state={state} source={src}')
        sys.exit(0 if state == 'running' else 1)
print('no Snapshot stream')
sys.exit(1)
