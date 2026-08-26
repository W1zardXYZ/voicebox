import { useMutation } from '@tanstack/react-query';
import { apiClient } from '@/lib/api/client';
import type { WhisperModelSize } from '@/lib/api/types';
import type { LanguageCode } from '@/lib/constants/languages';

export function useTranscription() {
  return useMutation({
    mutationFn: ({
      file,
      language,
      model,
      engine,
    }: {
      file: File;
      language?: LanguageCode;
      model?: WhisperModelSize;
      engine?: 'whisper' | 'parakeet';
    }) => apiClient.transcribeAudio(file, language, model, engine),
  });
}