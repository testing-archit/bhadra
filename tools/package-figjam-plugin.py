"""Build a domain-restricted development plugin bundle, without dependencies."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlparse
from zipfile import ZipFile, ZIP_DEFLATED

parser = argparse.ArgumentParser()
parser.add_argument('--origin', required=True)
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
with ZipFile(output, 'w', ZIP_DEFLATED) as bundle:
    bundle.writestr('manifest.json', json.dumps(manifest, indent=2))
    bundle.writestr('code.js', (root/'integrations/figjam/code.js').read_text().replace('__API_ORIGIN__', origin))
    bundle.write(root/'integrations/figjam/ui.html', 'ui.html')
    bundle.writestr('README.txt', 'Unzip. In Figma desktop, open your FigJam file, then Plugins > Development > Import plugin from manifest. Select manifest.json. Run Wilco meeting commands. Paste the matching file link and the one-time code from your Wilco live meeting. Keep the plugin open. Use Figma Share to invite collaborators. This development plugin is not published in Figma Community. If your organization requires plugin approval, ask its Figma administrator.\n')
print(output)
