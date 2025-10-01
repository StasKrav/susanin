#!/bin/bash
mkdir -p versions
STAMP=$(date +"%Y-%m-%d_%H-%M-%S")
COMMENT=$1
if [ -n "$COMMENT" ]; then
  COMMENT="_$(echo $COMMENT | tr ' ' '_')"
fi
cp main.py "versions/main_${STAMP}${COMMENT}.py"
echo "✅ Сохранено: versions/main_${STAMP}${COMMENT}.py"
