#!/bin/bash
API="https://hanwoo.koreacentral.cloudapp.azure.com/muzzle/enroll"
declare -A NID=( [cow01]=000000000001 [cow06]=000000000006 \
                 [cow07]=000000000007 [cow09]=000000000009 [cow10]=000000000010 )
for c in "${!NID[@]}"; do
  D=~/data/muzzle_eval/crops/enroll/$c
  [ -d "$D" ] || { echo "[skip] $c 폴더 없음"; continue; }
  ARGS=(); n=0
  for f in $(ls "$D"/* | head -5); do ARGS+=(-F "files=@$f"); n=$((n+1)); done
  [ $n -eq 0 ] && { echo "[skip] $c 이미지 없음"; continue; }
  echo "--- $c (${NID[$c]}) 사진 ${n}장"
  curl -sS -X POST "$API" -F "national_id=${NID[$c]}" -F "barn_id=demo" \
       "${ARGS[@]}" -w "\nHTTP:%{http_code}\n"
done
