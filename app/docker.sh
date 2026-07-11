#!/bin/sh
export PACKAGES_MIRROR="${PACKAGES_MIRROR:-}"
export PIP_MIRROR="${PIP_MIRROR:-}"

INSTALL_PACKAGES_SPACED=$(echo "${INSTALL_PACKAGES:-}" | tr '|' ' ')

NEED_APK=false
if [ -n "$INSTALL_PACKAGES" ]; then
    NEED_APK=true
fi
if [ -n "$INSTALL_PIP_PACKAGES" ] && ! which python3 >/dev/null 2>&1; then
    NEED_APK=true
fi

if $NEED_APK; then
    if [ -n "$PACKAGES_MIRROR" ]; then
        sed -i "s/dl-cdn.alpinelinux.org/$PACKAGES_MIRROR/g" /etc/apk/repositories
    fi
    
    if [ -n "$INSTALL_PACKAGES" ]; then
        apk add --no-cache $INSTALL_PACKAGES_SPACED
    fi
    
    if [ -n "$INSTALL_PIP_PACKAGES" ] && ! which python3 >/dev/null 2>&1; then
        apk add --no-cache python3 py3-pip
    fi
fi

if [ -n "$INSTALL_PIP_PACKAGES" ]; then
    if ! which python3 >/dev/null 2>&1; then
        echo "Error: Python 3 not found, cannot install Python packages."
        exit 1
    fi
    
    PYTHON=$(which python3)
    export PYTHON
    
    $PYTHON -c "
import os
import subprocess

pip_mirror = os.environ.get('PIP_MIRROR', '')
python_path = os.environ.get('PYTHON', 'python3')
install_pip_env = os.environ.get('INSTALL_PIP_PACKAGES', '')

package_list = [pkg.strip() for pkg in install_pip_env.split('|') if pkg.strip()]

for package_name in package_list:
    try:
        __import__(package_name)
        print(f'{package_name} already installed')
    except ImportError:
        try:
            cmd = [python_path, '-m', 'pip', 'install', '--break-system-packages', '--root-user-action', 'ignore', package_name]
            if pip_mirror:
                cmd.extend(['-i', pip_mirror])
            subprocess.check_call(cmd)
            print(f'Installed {package_name}')
        except Exception as e:
            print(f'Error installing {package_name}: {str(e)}')
            break
"
fi

exec "$@"