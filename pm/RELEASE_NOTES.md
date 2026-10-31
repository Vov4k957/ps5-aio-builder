Один ELF для PM 0.6.3. При пустой установке запускает резервный nanoDNS и через штатное «Управление источниками» скачивает восемь публичных нагрузок в отдельные слоты PM. При следующих запусках скачиваются только отсутствующие или изменившиеся файлы.

Порядок запуска — nanoDNS, локальный kstuff при наличии, ELF Loader, FTP Server (Drakmor stable), Web Server, ShadowMountPlus, Hush, Dump Forge, YT Blocker. Между нагрузками 1 с, перед YT Blocker 3 с. Если YouTube открыт, блокер пропускается.

Скачай `pm-autoupdate.elf`, импортируй его в PM и оставь его единственным включённым пунктом автозагрузки PM. Настройки встроены. [Инструкция](https://github.com/Vov4k957/ps5-aio-builder/blob/main/pm/README_RU.md) · [JSON для PM](https://raw.githubusercontent.com/Vov4k957/ps5-aio-builder/main/pm/payloads.json)

Аппаратный запуск на PS5 13.60 требует проверки.
