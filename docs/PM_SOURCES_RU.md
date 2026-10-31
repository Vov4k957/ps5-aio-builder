# Отдельные источники для Payload Manager v0.6.3

Для PM AutoUpdate нужен только [единый каталог из восьми нагрузок](https://raw.githubusercontent.com/Vov4k957/ps5-aio-builder/main/pm/payloads.json). Управляющий ELF добавляет его сам. Адреса ниже оставлены для пользователей, уже подключивших отдельные источники.

Эти URL вставляются **по одному** в поле **Настройки → Управление источниками → Добавить источник**. Это JSON-каталоги с одним публичным ELF каждый. Обычные страницы GitHub Releases в поле добавления источника не подходят.

| Нагрузка | Прямая ссылка на JSON-источник |
|---|---|
| ELF Loader | `https://raw.githubusercontent.com/Vov4k957/ps5-aio-builder/main/pm-sources/elfldr.json` |
| FTP Server | `https://raw.githubusercontent.com/Vov4k957/ps5-aio-builder/main/pm-sources/ftpsrv.json` |
| nanoDNS | `https://raw.githubusercontent.com/Vov4k957/ps5-aio-builder/main/pm-sources/nanodns.json` |
| Web Server | `https://raw.githubusercontent.com/Vov4k957/ps5-aio-builder/main/pm-sources/websrv.json` |
| ShadowMountPlus | `https://raw.githubusercontent.com/Vov4k957/ps5-aio-builder/main/pm-sources/shadowmountplus.json` |
| YT Blocker | `https://raw.githubusercontent.com/Vov4k957/ps5-aio-builder/main/pm-sources/yt-blocker.json` |
| Hush | `https://raw.githubusercontent.com/Vov4k957/ps5-aio-builder/main/pm-sources/hush.json` |
| Dump Forge | `https://raw.githubusercontent.com/Vov4k957/ps5-aio-builder/main/pm-sources/dump-forge.json` |

**Приватный kstuff1.13-fpkg-dr-test8-rest-fast.elf не включён.** Он предоставлен пользователем отдельно; в публичный репозиторий, GitHub Releases или Actions artifacts его публиковать нельзя. Его можно импортировать локально в PM. Не подменять на публичный EchoStretch v1.11.

Каждые 10 минут по расписанию GitHub Actions обновляет общий каталог из релизов авторов. Восемь отдельных адресов получают данные из того же снимка с прежними идентификаторами слотов. FTP следует стабильной ветке Drakmor. YT Blocker следует опубликованным релизам Epinorr. В очередь запуска его ставят последним. [Порядок запуска и установка](../pm/README_RU.md)
