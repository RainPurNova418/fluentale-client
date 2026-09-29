# FluentTale Client

![License](https://img.shields.io/badge/license-GPLv3-blue.svg)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey.svg)
![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)
![PySide6](https://img.shields.io/badge/PySide6-6.5%2B-green.svg)
[![Release](https://img.shields.io/github/v/release/RainPurNova418/fluentale-client?include_prereleases&label=release)](https://github.com/RainPurNova418/fluentale-client/releases)
[![Stars](https://img.shields.io/github/stars/RainPurNova418/fluentale-client?style=social)](https://github.com/RainPurNova418/fluentale-client/stargazers)
[![Issues](https://img.shields.io/github/issues/RainPurNova418/fluentale-client)](https://github.com/RainPurNova418/fluentale-client/issues)

基于 [PySide6](https://pypi.org/project/PySide6/) 和 [QFluentWidgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets) 构建的 FimTale 第三方客户端。

-----

## 功能

目前还只是个普通的阅读器而已捏。

## 要求

- Windows 10 及以上
- Python 3.10+（仅开发）
- **未被封禁**的 FimTale 用户账户（用于生成 APIKey / APIPass）

## 使用

### 发布版

前往 [Releases](https://github.com/RainPurNova418/fluentale-client/releases) 下载最新的 zip 包，解压后运行 `FluentTaleClient.exe`。

### 从源码运行

```bash
git clone https://github.com/RainPurNova418/fluentale-client.git
cd fluentale-client
pip install -r requirements.txt
python main.py
```

### 构建

```bash
pip install pyinstaller
python -m PyInstaller --noconfirm FluentTaleClient.spec
```
