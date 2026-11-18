import json
import sys
from pathlib import Path
from builder import ArtifactSpec,build_artifact
spec=ArtifactSpec(**json.load(sys.stdin))
result=build_artifact(spec,Path('/tmp/job'),basename='document')
sys.stdout.buffer.write(result.path.read_bytes())
