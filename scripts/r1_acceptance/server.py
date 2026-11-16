"""Isolated acceptance server: instrument Python outbound socket attempts before app import."""
import ipaddress
import json
import os
from pathlib import Path
import sys

log=Path(os.environ['R1_NETWORK_AUDIT'])
log.parent.mkdir(parents=True,exist_ok=True)
with log.open('a') as stream:stream.write(json.dumps({'event':'observer_started','pid':os.getpid()})+'\n')
def audit(event,args):
    if event not in ('socket.connect','socket.getaddrinfo'):return
    address=args[1] if event=='socket.connect' else args[0]
    host=address[0] if isinstance(address,tuple) else address
    if not isinstance(host,str):return
    try:local=ipaddress.ip_address(host).is_loopback
    except ValueError:local=host=='localhost'
    with log.open('a') as stream:stream.write(json.dumps({'event':event,'address':repr(address),'local':local})+'\n')
    if not local:raise RuntimeError('acceptance observed and blocked external network attempt')
sys.addaudithook(audit)
# Match start-trial.sh: storage directories must exist before database path resolution.
for relative in ['uploads','archive','backups','cache','tmp','analysis-assets','temp-frames']:
    (Path('/data')/relative).mkdir(parents=True,exist_ok=True)
import uvicorn
uvicorn.run('app.main:app',host='0.0.0.0',port=8000,workers=1)
