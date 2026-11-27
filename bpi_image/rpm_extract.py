import subprocess
import tempfile

def extract(rpm,directory):
    # Consume the complete RPM stream before cpio exits at TRAILER!!!. This
    # avoids SIGPIPE on packages whose payload has substantial trailing padding.
    with tempfile.TemporaryFile() as payload:
        subprocess.run(['rpm2cpio',str(rpm)],stdout=payload,check=True)
        payload.seek(0)
        subprocess.run(['cpio','--quiet','-idm','--no-absolute-filenames','--no-preserve-owner'],
            stdin=payload,cwd=directory,check=True)

