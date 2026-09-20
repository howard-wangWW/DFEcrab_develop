---
name: video-frames
description: 当用户需要从视频中提取帧或创建缩略图时使用，如"提取视频的某一帧"、"获取视频截图"、"创建视频缩略图"、"截取视频片段"、"从视频中提取图片"等。
---

# Video Frames 技能

使用 ffmpeg 提取视频帧或创建缩略图。

## 使用场景

当用户说：
- "提取这个视频的第10秒画面"
- "获取视频的缩略图"
- "截取视频片段"
- "从视频中提取帧"
- "把这个视频转成图片"

## 使用方式

### 提取第一帧
```bash
ffmpeg -i video.mp4 -vframes 1 output.jpg
```

### 在指定时间提取帧
```bash
ffmpeg -i video.mp4 -ss 00:00:10 -vframes 1 output.jpg
```

### 创建缩略图（多帧）
```bash
ffmpeg -i video.mp4 -vf "fps=1/10" thumb%03d.jpg
```

### 截取视频片段
```bash
ffmpeg -i video.mp4 -ss 00:00:05 -t 00:00:10 -c copy clip.mp4
```

### 提取关键帧
```bash
ffmpeg -i video.mp4 -vf "select='eq(pict_type,PICT_TYPE_I)'" -vsync vfr thumb%03d.jpg
```

## 常用参数

| 参数 | 功能 |
|------|------|
| `-i input.mp4` | 输入视频 |
| `-ss 00:00:10` | 开始时间 |
| `-t 00:00:05` | 持续时间 |
| `-vframes 1` | 输出帧数 |
| `-q:v 2` | 输出质量 (1-31，越低越好) |

## 输出格式

- **.jpg** - 快速分享，文件小
- **.png** - 清晰UI帧，文件大

## 安装

如果 ffmpeg 不可用：
```bash
brew install ffmpeg  # macOS
apt install ffmpeg   # Ubuntu/Debian
```

## 注意事项

- 使用 `--time` 参数获取特定时间点的画面
- 缩略图序列可以用 `-vf fps=1/60` 每分钟一帧
- 高质量输出使用 `-q:v 1`
