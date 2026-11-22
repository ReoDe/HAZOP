"""화면 아이콘 불러오기. 아이콘은 Tabler Icons 3.51.0(MIT) 선 아이콘 원본이고 `resources/library/icons/tabler/`에 쓰는 것만 둔다.

    from hazop.app import icons
    button.setIcon(icons.icon("send", color="ui", size=16))     # Qt: QIcon (색은 tokens 이름이나 #RRGGBB, 기본은 본문 글자색 ink)
    html = icons.svg_inline("zoom-in", size=16)                 # 웹(뷰어·채팅 카드): 글자색(currentColor)을 따르는 <svg> 한 줄

- 없는 이름은 오류가 아니라 빈 아이콘(QIcon()·"")과 경고 로그(`hazop.app.icons`)다. 이름은 파일 이름에서 `.svg`를 뺀 것이고
  `names()`가 목록(`manifest.json`)을 준다. 이름에 경로 조각은 받지 않는다.
- QIcon은 요청한 크기의 1~3배(1.25·1.5·2 …)를 새로 그려 담아 두어, 125% 같은 배율에서도 작은 그림을 늘려 흐려지지 않는다.
- 원본은 한 바이트도 바꾸지 않는다(tests/test_icons.py). 색·크기는 읽을 때 문자열에서 바꾼다.
"""

import functools
import json
import logging
import os
import re

from hazop import paths
from hazop.app import tokens

LOG = logging.getLogger("hazop.app.icons")
DEFAULT_COLOR = "ink"
DEFAULT_SIZE = 16
RATIOS = (1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0)   # 화면 배율(100~300%)마다 따로 그려 둔다
_NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_BACKGROUND = re.compile(r'\s*<path stroke="none" d="M0 0h24v24H0z" fill="none"\s*/>')   # 받은 파일의 투명 바탕 경로


def _dir():
    return paths.folder("icons", "tabler")


@functools.lru_cache(maxsize=1)
def _names():
    try:
        with open(os.path.join(_dir(), "manifest.json"), encoding="utf-8") as fh:
            return tuple(sorted(json.load(fh)["icons"]))
    except (OSError, ValueError, KeyError):
        LOG.warning("아이콘 목록을 읽을 수 없음: %s", _dir())
        return ()


def names():
    """넣어 둔 아이콘 이름 목록(정렬)."""
    return list(_names())


def icon_path(name):
    """아이콘 파일 경로. 없는 이름(목록 밖, 경로 조각 포함)이면 None."""
    if not isinstance(name, str) or not _NAME.match(name) or name not in _names():
        return None
    return os.path.join(_dir(), name + ".svg")


def _source(name):
    p = icon_path(name)
    if p is None:
        LOG.warning("없는 아이콘 이름: %r", name)
        return None
    try:
        with open(p, encoding="utf-8") as fh:
            return fh.read()
    except OSError as exc:
        LOG.warning("아이콘을 읽을 수 없음: %s (%s)", name, exc)
        return None


def _hex(color):
    """토큰 이름이나 #RRGGBB → '#rrggbb'. 모르는 값이면 기본 색."""
    if isinstance(color, str):
        if _HEX.match(color):
            return color.lower()
        if color in tokens.COLORS and _HEX.match(tokens.COLORS[color]):
            return tokens.c(color)
    return tokens.c(DEFAULT_COLOR)


def _sized(svg, size):
    return re.sub(r'(<svg\b[^>]*?)\swidth="\d+"(\s+height=)"\d+"', r'\1 width="%d"\2"%d"' % (size, size), svg, count=1)


def svg_text(name, color=None, size=DEFAULT_SIZE):
    """색을 정한 SVG 문자열(Qt가 그릴 용도). 없는 이름이면 ""."""
    src = _source(name)
    if src is None:
        return ""
    return _sized(src.replace("currentColor", _hex(color)), int(size))


def svg_inline(name, size=DEFAULT_SIZE):
    """웹에 넣는 한 줄 <svg>. 선 색은 currentColor라 CSS 글자색을 따른다. 받은 파일의 class 속성과 투명 바탕 경로는 뺀다. 없는 이름이면 ""."""
    src = _source(name)
    if src is None:
        return ""
    src = _BACKGROUND.sub("", src)
    src = re.sub(r'\s+class="[^"]*"', "", src)
    src = _sized(src, int(size))
    src = re.sub(r"\s*\n\s*", " ", src.strip())
    src = re.sub(r"\s{2,}", " ", src).replace(" >", ">").replace("<svg ", '<svg aria-hidden="true" ', 1)
    return src.replace(" />", "/>")


@functools.lru_cache(maxsize=512)
def _qicon(name, color, size):
    from PySide6.QtCore import QByteArray, Qt
    from PySide6.QtGui import QIcon, QPainter, QPixmap
    from PySide6.QtSvg import QSvgRenderer
    text = svg_text(name, color, size)
    if not text:
        return QIcon()
    renderer = QSvgRenderer(QByteArray(text.encode("utf-8")))
    ic = QIcon()
    for ratio in RATIOS:
        px = max(1, round(size * ratio))
        pm = QPixmap(px, px)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        renderer.render(p)
        p.end()
        pm.setDevicePixelRatio(ratio)
        ic.addPixmap(pm)
    return ic


def icon(name, color=None, size=DEFAULT_SIZE):
    """QIcon. color = 토큰 이름이나 #RRGGBB(기본 ink), size = 100%일 때의 한 변 화소. 없는 이름이면 빈 QIcon과 경고 로그."""
    if icon_path(name) is None:
        LOG.warning("없는 아이콘 이름: %r", name)
        from PySide6.QtGui import QIcon
        return QIcon()
    return _qicon(name, _hex(color), int(size))
