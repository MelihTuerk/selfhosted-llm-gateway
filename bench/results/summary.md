| Run | Hardware | Model | Parallel | TTFT median | TTFT p95 | Tokens/s per request | Tokens/s total |
|---|---|---|---:|---:|---:|---:|---:|
| cpu-q4 | i5-8600K (6 cores) | qwen2.5-7b-instruct | 1 | 5.67 s | 6.18 s | 7.2 | 5.5 |
| cpu-q4 | i5-8600K (6 cores) | qwen2.5-7b-instruct | 2 | 11.12 s | 11.15 s | 4.3 | 6.2 |
| cpu-q4 | i5-8600K (6 cores) | qwen2.5-7b-instruct | 4 | 21.85 s | 22.09 s | 5.6 | 11.5 |
| gpu-q4 | GTX 1060 6GB | qwen2.5-7b-instruct | 1 | 0.74 s | 0.74 s | 24.3 | 21.5 |
| gpu-q4 | GTX 1060 6GB | qwen2.5-7b-instruct | 2 | 1.40 s | 1.49 s | 17.6 | 27.2 |
| gpu-q4 | GTX 1060 6GB | qwen2.5-7b-instruct | 4 | 2.56 s | 2.58 s | 16.0 | 48.8 |
| gpu-q5 | GTX 1060 6GB | qwen2.5-7b-instruct | 1 | 0.78 s | 0.79 s | 21.6 | 19.2 |
| gpu-q5 | GTX 1060 6GB | qwen2.5-7b-instruct | 2 | 1.48 s | 1.57 s | 15.6 | 24.4 |
| gpu-q5 | GTX 1060 6GB | qwen2.5-7b-instruct | 4 | 2.71 s | 2.73 s | 14.9 | 45.7 |
