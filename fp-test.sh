#!/usr/bin/env bash
# Banco de pruebas del driver focaltech_moh (sin instalar nada en el sistema).
#   ./fp-test.sh enroll [dedo]   -> enrola y archiva las imagenes
#   ./fp-test.sh verify [dedo]   -> verifica
#   ./fp-test.sh clean           -> borra la plantilla local
set -e
PROJ="$(cd "$(dirname "$0")" && pwd)"
BASE="$PROJ/libfprint"
export LD_LIBRARY_PATH="$BASE/build/libfprint"
export G_MESSAGES_DEBUG=all
cd "$PROJ"
CMD="${1:-enroll}"; FINGER="${2:-6}"
case "$CMD" in
  enroll)
    rm -f test-storage.variant
    echo "$FINGER" | "$BASE/build/examples/enroll" 2>&1 \
      | grep -viE "SSM-DEBUG|temperature model|No driver found|INT_STATUS: 0x00"
    if [ -f test-storage.variant ]; then
      mkdir -p capturas
      cp test-storage.variant "capturas/enroll-$(date +%H%M%S).variant"
      echo ">>> plantilla archivada en capturas/"
    fi ;;
  verify)
    echo "$FINGER" | "$BASE/build/examples/verify" 2>&1 \
      | grep -viE "SSM-DEBUG|temperature model|No driver found|INT_STATUS: 0x00" ;;
  clean) rm -f test-storage.variant; echo "plantilla local borrada" ;;
  *) echo "uso: $0 enroll|verify|clean [n_dedo]"; exit 1 ;;
esac
