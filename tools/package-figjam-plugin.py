"""Build a domain-restricted development plugin bundle, without dependencies."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlparse
from zipfile import ZipFile, ZIP_DEFLATED

parser = argparse.ArgumentParser()
parser.add_argument('--origin', required=True)
parser.add_argument('--plugin-id', help='Your Figma-issued development plugin ID, when already registered')
parser.add_argument('--output', default='frontend/public/downloads/wilco-figjam.zip')
args = parser.parse_args()
url = urlparse(args.origin)
if url.scheme != 'https' or not url.netloc or url.path not in ('', '/') or url.query or url.fragment or url.username:
    parser.error('Use the HTTPS origin of your Wilco app.')
origin = args.origin.rstrip('/')
root = Path(__file__).resolve().parents[1]
output = root / args.output
output.parent.mkdir(parents=True, exist_ok=True)
manifest = {'name':'Wilco meeting commands','api':'1.0.0','editorType':['figjam'],'main':'code.js','ui':'ui.html',
            'documentAccess':'dynamic-page','networkAccess':{'allowedDomains':[origin]}}
if args.plugin_id:
    import re
    if not re.fullmatch(r'[0-9]{6,30}', args.plugin_id):
        parser.error('Use the numeric plugin ID assigned by Figma.')
    manifest['id'] = args.plugin_id
with ZipFile(output, 'w', ZIP_DEFLATED) as bundle:
    bundle.writestr('manifest.json', json.dumps(manifest, indent=2))
    bundle.writestr('code.js', (root/'integrations/figjam/code.js').read_text().replace('__API_ORIGIN__', origin))
    bundle.write(root/'integrations/figjam/ui.html', 'ui.html')
    bundle.write(root/'integrations/figjam/configure.py', 'configure.py')
    bundle.writestr('README.txt', '''ONE-TIME SETUP
1. In Figma desktop, choose Plugins > Development > New plugin. Name it Wilco meeting commands, choose FigJam, and save the generated folder. Figma assigns your development plugin ID.
2. Unzip this download. From this extracted folder run:
   python3 configure.py --from-manifest "/path/to/figma-generated/manifest.json"
   This updates only this bundle's manifest with your own Figma-issued ID.
3. Plugins > Development > Import plugin from manifest: select THIS bundle's updated manifest.json. Replace the previous development entry if Figma asks.
4. Open your FigJam file and run Wilco meeting commands. Paste that file's link and the one-time code from your Wilco live meeting. Keep the plugin open.

Use Figma Share to choose collaborators. Only the person hosting this plugin needs to install it. This development plugin is not published in Figma Community; your organization may require its approval. No Figma password or personal API key is requested.
''')
print(output)
