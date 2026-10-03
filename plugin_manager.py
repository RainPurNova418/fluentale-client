# plugin_manager.py
'''插件管理器，嗯对。'''
import importlib
import importlib.util
import sys
from pathlib import Path
from typing import List, Dict, Optional, Type

from base_plugin import BasePlugin, PluginType
from toolmethods import log, log_warning, log_error, log_success


class PluginManager:
    def __init__(self, plugins_root: str, services):
        self.plugins_root = Path(plugins_root)
        self.services = services
        self.plugins: Dict[PluginType, List[BasePlugin]] = {
            PluginType.UI: [],
            PluginType.SERVICE: [],
            PluginType.TOOL: [],
        }

    def discover_and_load(self) -> Dict[PluginType, List[BasePlugin]]:
        if not self.plugins_root.exists():
            self.plugins_root.mkdir(parents=True)
            log("插件目录不存在，已自动创建", "WARNING")
            return self.plugins

        # plugins_root 的父目录进 sys.path，让 plugins.xxx 能被正常 import
        parent = str(self.plugins_root.parent.resolve())
        if parent not in sys.path:
            sys.path.insert(0, parent)

        default_dir = self.plugins_root / "_default"
        if default_dir.exists():
            log("加载系统默认插件 (_default)", "INFO")
            self._scan_container(default_dir, is_default=True)

        # 这些目录放在 plugins/ 下，但不是插件，跳过
        _SKIP_DIRS = {"devtest", "__pycache__"}

        for item in sorted(self.plugins_root.iterdir()):
            if item.name.startswith("_") or not item.is_dir():
                continue
            if item.name in _SKIP_DIRS:
                log(f"跳过非插件目录: {item.name}", "DEBUG")
                continue
            log(f"扫描普通插件目录: {item.name}", "DEBUG")
            self._scan_container(item, is_default=False)

        return self.plugins

    # ── 扫描 ──

    def _scan_container(self, directory: Path, is_default: bool):
        """容器目录下每个 .py 文件或子目录，都是一个插件候选"""
        for item in sorted(directory.iterdir()):
            if item.name.startswith("."):
                continue

            if item.is_file() and item.suffix == ".py":
                if item.name == "__init__.py":
                    continue
                self._load_from_file(item, is_default)

            elif item.is_dir():
                if item.name.startswith("_"):
                    # 下划线开头：当作纯容器递归（比如 _default 内部）
                    self._scan_container(item, is_default)
                    continue

                entry = self._find_package_entry(item)
                if entry is not None:
                    self._load_from_package(item, entry, is_default)

    def _find_package_entry(self, package_dir: Path) -> Optional[Path]:
        """
        找插件包的入口文件：
        1. __init__.py
        2. <dirname>.py
        3. 目录下唯一的 .py
        4. 都不满足 → 报错返回 None
        """
        entry = package_dir / "__init__.py"
        if entry.is_file():
            return entry

        entry = package_dir / f"{package_dir.name}.py"
        if entry.is_file():
            return entry

        py_files = sorted(
            f for f in package_dir.glob("*.py")
        )
        if len(py_files) == 1:
            return py_files[0]

        if not py_files:
            log_error(
                f"插件目录 {package_dir} 中没有可用的入口文件。\n"
                f"  需要以下之一：\n"
                f"    - __main__.py\n"
                f"    - {package_dir.name}.py\n"
                f"    - 目录下唯一的 .py 文件"
            )
        else:
            names = ", ".join(f.name for f in py_files)
            log_error(
                f"插件目录 {package_dir} 入口不明确，发现多个 .py: {names}\n"
                f"  请使用 __main__.py 或 {package_dir.name}.py 指定入口"
            )
        return None

    # ── 加载 ──

    def _load_from_file(self, py_file: Path, is_default: bool):
        module_name = f"_plugin_{py_file.parent.name}_{py_file.stem}"
        try:
            module = self._import_from_file(py_file, module_name)
        except Exception as e:
            log_error(f"加载插件失败 {py_file.name}: {e}")
            return
        self._register(module, str(py_file.parent), py_file.name, is_default)

    def _load_from_package(self, package_dir: Path, entry: Path, is_default: bool):
        has_init = (package_dir / "__init__.py").is_file()
        try:
            if has_init:
                module = self._import_from_package(package_dir, entry)
            else:
                module_name = f"_plugin_{package_dir.name}_{entry.stem}"
                module = self._import_from_file(
                    entry, module_name,
                    submodule_search_locations=[str(package_dir)],
                )
        except Exception as e:
            log_error(f"加载插件包失败 {package_dir.name}: {e}")
            return
        self._register(module, str(package_dir), package_dir.name, is_default)

    def _import_from_file(self, py_file: Path, module_name: str,
                          submodule_search_locations: Optional[List[str]] = None):
        spec = importlib.util.spec_from_file_location(
            module_name, py_file,
            submodule_search_locations=submodule_search_locations,
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"无法创建模块 spec: {py_file}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module

    def _import_from_package(self, package_dir: Path, entry: Path):
        if entry.stem == "__main__":
            module_name = f"{package_dir.name}.__main__"
        else:
            module_name = f"{package_dir.name}.{entry.stem}"
        return importlib.import_module(module_name)

    # ── 注册 ──

    def _register(self, module, plugin_path: str, source_name: str, is_default: bool):
        classes = self._find_plugin_classes(module)
        if not classes:
            log_warning(f"{source_name} 中没有找到 BasePlugin 子类")
            return
        if len(classes) > 1:
            names = ", ".join(c.__name__ for c in classes)
            log_error(f"{source_name} 中发现多个 BasePlugin 子类: {names}\n"
                      f"  每个插件只能有一个插件类")
            return

        plugin_class = classes[0]
        try:
            instance = plugin_class(plugin_path)
        except Exception as e:
            log_error(f"实例化 {source_name} 失败: {e}")
            return

        if not instance.plugin_types:
            instance.plugin_types = [PluginType.UI]
        instance.set_services(self.services)

        for ptype in instance.plugin_types:
            self.plugins.setdefault(ptype, []).append(instance)

        log(
            f"加载 {'[默认] ' if is_default else ''}插件: {instance.plugin_id} "
            f"(来源: {source_name}, 类型: {[t.value for t in instance.plugin_types]})",
            "SUCCESS" if is_default else "INFO"
        )

    def _find_plugin_classes(self, module) -> List[Type[BasePlugin]]:
        result = []
        for attr_name in dir(module):
            if attr_name.startswith("_"):
                continue
            attr = getattr(module, attr_name)
            if (isinstance(attr, type)
                    and issubclass(attr, BasePlugin)
                    and attr is not BasePlugin
                    and attr.__module__ == module.__name__):
                result.append(attr)
        return result