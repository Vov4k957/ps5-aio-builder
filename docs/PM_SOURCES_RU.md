# Отдельные источники для Payload Manager v0.6.3

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

Каталоги формируются скриптом `scripts/update_pm_sources.py`. GitHub Actions `.github/workflows/update-pm-sources.yml` проверяет версии ежедневно в 04:13 UTC (без гарантии точной минуты запуска) и при ручном запуске. При отсутствии изменений ничего не коммитит. Проверка обновлений каталога в PM **не равнозначна автоматической установке обновлений до автозагрузки**. Авторские новые версии могут оказаться несовместимы с PS5 13.60; перед установкой изучать изменения. YT Blocker намеренно закреплён за **v1.0.2** по ранее заданному требованию.

Каждый каталог содержит `version`, `url`, `filename`, `checksum` SHA-256 и стабильный `id`. При отсутствии SHA-256 в GitHub release-asset API автоматическое обновление каталога прерывается, чтобы не публиковать непроверенный ELF.

Последнее ручное заполнение: 31.10.2026.
