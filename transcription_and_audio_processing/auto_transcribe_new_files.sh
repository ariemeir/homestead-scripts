#!/usr/bin/env bash
set -euo pipefail

# --------- CONFIG ---------
REMOTE_DIR='gdrive:business/communications/Conversation Notes'
POLL_SECS=60
MIN_AGE='2m'
TMP_ROOT="/tmp/whisperx_inbox"
STATE_FILE="$HOME/.whisperx_processed_ids.txt"
LOCK_FILE="/tmp/whisperx_runner.lock"

INCLUDE_AUDIO=(
  "--include" "*.m4a"
  "--include" "*.mp3"
  "--include" "*.wav"
  "--include" "*.aac"
)

WHISPER_MODEL="large-v3"
WHISPER_DEVICE="cpu"
WHISPER_COMPUTE="int8"

# --------- SETUP ---------
command -v rclone >/dev/null || { echo "rclone not found"; exit 1; }
command -v jq >/dev/null || { echo "jq not found (brew install jq)"; exit 1; }
command -v whisperx >/dev/null || { echo "whisperx not found"; exit 1; }
: "${HF_TOKEN:?HF_TOKEN not set in environment}"

mkdir -p "$TMP_ROOT"
touch "$STATE_FILE"

# Single-instance lock
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "Already running."
  exit 0
fi

log() { echo "$(date '+%F %T') $*"; }

is_processed_id() {
  local id="$1"
  grep -qxF "$id" "$STATE_FILE" 2>/dev/null
}

mark_processed_id() {
  local id="$1"
  if ! is_processed_id "$id"; then
    echo "$id" >> "$STATE_FILE"
  fi
}

# Build a set of existing SRT basenames in the folder (once per polling cycle)
# Output: lines like "foo.srt"
list_existing_srt_names() {
  rclone lsf "$REMOTE_DIR" --files-only --include "*.srt" 2>/dev/null || true
}

# For an audio path like "abc.mp3", returns "abc.srt"
audio_to_srt_name() {
  local audio_path="$1"
  echo "$(basename "${audio_path%.*}.srt")"
}

transcribe_and_upload() {
  local audio_path="$1"
  local audio_id="$2"

  local job_dir="$TMP_ROOT/$audio_id"
  mkdir -p "$job_dir"
  local local_audio="$job_dir/$(basename "$audio_path")"

  log "Downloading: $audio_path"
  rclone copyto "$REMOTE_DIR/$audio_path" "$local_audio"

  log "Transcribing: $(basename "$audio_path")"
  local whisper_log="$job_dir/whisperx.log"
 
  whisperx "$local_audio" \
  --model "$WHISPER_MODEL" \
  --device "$WHISPER_DEVICE" \
  --compute_type "$WHISPER_COMPUTE" \
  --diarize \
  --hf_token "$HF_TOKEN" \
  --output_format srt \
  --output_dir "$job_dir" \
  2>&1 | tee "$whisper_log"

  local base="$(basename "${audio_path%.*}")"
  local local_srt="$job_dir/${base}.srt"
  if [[ ! -f "$local_srt" ]]; then
    log "ERROR: SRT not found after transcription: $local_srt (see $whisper_log)"
    return 1
  fi

  local remote_srt="${audio_path%.*}.srt"
  log "Uploading: $remote_srt"
  rclone copyto "$local_srt" "$REMOTE_DIR/$remote_srt"

  mark_processed_id "$audio_id"
  rm -rf "$job_dir"

  log "Done: $audio_path"
}

process_all_once() {
  local files_json
  if ! files_json="$(rclone lsjson "$REMOTE_DIR" \
      --files-only \
      --max-depth 1 \
      --min-age "$MIN_AGE" \
      "${INCLUDE_AUDIO[@]}" \
      --metadata 2>/dev/null)"; then
    log "ERROR: Failed to lsjson (check REMOTE_DIR path + rclone permissions)"
    return 1
  fi

  # Snapshot SRTs once per cycle so we don't re-list for every audio file
  local existing_srts
  existing_srts="$(list_existing_srt_names)"

  # Iterate every audio file found this cycle
  # We output TSV: Path<TAB>ID
  echo "$files_json" | jq -r '.[] | select(.IsDir==false) | [.Path, .ID] | @tsv' | \
  while IFS=$'\t' read -r audio_path audio_id; do
    [[ -z "${audio_path:-}" || "$audio_path" == "null" ]] && continue
    [[ -z "${audio_id:-}"   || "$audio_id"   == "null" ]] && continue

    # Skip already-processed IDs
    if is_processed_id "$audio_id"; then
      continue
    fi

    # If SRT exists, mark processed and skip forever
    srt_name="$(audio_to_srt_name "$audio_path")"
    if echo "$existing_srts" | grep -qxF "$srt_name"; then
      log "SRT exists; ignoring: $audio_path"
      mark_processed_id "$audio_id"
      continue
    fi

    # Otherwise process it (blocks until whisperx completes)
    transcribe_and_upload "$audio_path" "$audio_id"
  done
}

# --------- MAIN LOOP ---------
log "Watching: $REMOTE_DIR (poll every ${POLL_SECS}s, min-age $MIN_AGE)"
while true; do
  if ! process_all_once; then
    log "Loop error (continuing)."
  fi
  sleep "$POLL_SECS"
done
