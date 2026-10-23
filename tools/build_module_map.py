# -*- coding: utf-8 -*-
"""Build the module responsibility map and static cross-module call inventory."""
import argparse
import ast
import json
import re
from pathlib import Path
from xml.etree import ElementTree as E


ROOT = Path(__file__).resolve().parents[1]
PURPOSES = {
    'appearance_xml': 'Цвета, шрифты и оформление элементов.',
    'automatic_deletion': 'Поиск отсутствующих детей и сборка изменения с удалениями.',
    'tabular_section_xml': 'Табличные части справочников и документов.',
    'child_object_xml': 'Ссылки владельца на отдельно хранимые дочерние объекты.',
    'choice_list_xml': 'Списки выбора и их значения.',
    'commonmodule_serializer': 'Изменение общего модуля, включая его текст и описание.',
    'configuration_batch': 'Объединение подготовленных изменений в один пакет.',
    'configuration_commit': 'Подготовка полной выгрузки: создания, изменения, зависимости и удаления.',
    'configuration_export': 'Инвентаризация файлов выгрузки и определение операций.',
    'configuration_xml': 'Свойства корня конфигурации и преобразование его полного XML.',
    'configuration_serializer': 'Сборка пакета изменения корня конфигурации.',
    'object_creation_serializer': 'Сборка создания объекта, его форм и связанных изменений.',
    'delete_object_serializer': 'Сборка явного удаления объекта и изменения его владельца.',
    'external_data': 'Чтение тел объектов и внешних потоков из пакета версии.',
    'external_dependencies': 'Проверка итоговых потоков форм и СКД на ссылки к удаляемым объектам, типам и значениям.',
    'metadata_object_xml': 'Общий механизм создания и изменения нативного тела по полному XML; выгрузка поддержанных структур.',
    'metadata_common_xml': 'Прямое чтение и запись общих свойств метаданных без промежуточных объектов.',
    'inline_attribute_xml': 'Общие свойства, типы и проверенные шаблоны встроенных реквизитов.',
    'form_attribute_types': 'Типы реквизитов формы, включая составные и коллекционные.',
    'form_definition_xml': 'Описание формы: UUID, имя, свойства и нативное тело описания.',
    'form_dependencies': 'Поиск форм, которые нужно пересобрать при изменении владельца.',
    'metadata_owner_change': 'Общие свойства и отдельно хранимые коллекции существующего владельца при неполном XML-профиле.',
    'metadata_owner_profiles': 'Общий реестр проверенных нативных структур владельцев, включая контейнеры без форм.',
    'opaque_owner_references': 'Проверка эквивалентности известных XML-ссылок неполных профилей при переименовании цели с сохранением нативного UUID.',
    'inline_command_xml': 'Владение потоками модулей встроенных команд.',
    'inline_metadata_xml': 'Общие свойства и рекурсивные дочерние коллекции встроенных метаданных.',
    'inline_object_xml': 'Реквизиты, измерения, ресурсы и другие встроенные коллекции.',
    'managed_form_bindings': 'Привязки данных формы к реквизитам и коллекциям владельца.',
    'managed_form_elements': 'Преобразование элементов управляемой формы.',
    'managed_form_profiles': 'Профили владельцев и структуры управляемых форм.',
    'managed_form_rules': 'Профильные правила свойств и событий формы и её элементов.',
    'managed_form_operations': 'Создание и изменение управляемой формы: версии, привязки, описание, интерфейс, модуль и пакет помещения.',
    'managed_form_xml': 'Преобразование полного Form.xml и текста модуля формы.',
    'metadata_classes': 'Получение справочника классов метаданных через Python-вход.',
    'metadata_context': 'Чтение updateInfo, проверка UUID и карты отдельно хранимых детей.',
    'metadata_identifiers': 'UUID классов, коллекций и служебных возможностей.',
    'metadata_localized_xml': 'Многоязычные строки метаданных.',
    'metadata_references': 'Разрешение ссылок из формы и определение требуемых снимков.',
    'metadata_structure': 'Карта классов, дочерних коллекций и их правил хранения.',
    'metadata_targets': 'Индекс текущих и итоговых объектов для разрешения ссылок.',
    'native_content': 'Общий результат преобразования: метаданные, тело, потоки и их версии; без упаковки пакета.',
    'native_references': 'Итоговые ссылки на типы и значения: подготовленные нативные определения либо проверенные исходные снимки/пакет версии.',
    'metadata_type_references': 'Ссылочные типы свойств Type: сопоставление XML-имён с UUID типов итоговой конфигурации.',
    'metadata_type_sets': 'Проверенные групповые типы платформы: XML TypeSet, постоянные UUID и запрет их подмены.',
    'metadata_field_lists': 'Полные списки полей метаданных: стандартные селекторы и UUID собственных реквизитов для поиска и блокировок.',
    'native_collection_editor': 'Изменение нативных коллекций по карте метаданных.',
    'native_metadata': 'Нативное дерево, текст, двоичные записи, сжатие и контейнер хранилища.',
    'object_change_serializer': 'Сборка изменения существующего объекта по полному XML.',
    'object_graph': 'Обход владения и замыкание зависимостей объектов.',
    'object_xml_profiles': 'Проверенные свойства, коллекции и модули классов объектов.',
    'object_file_content': 'Полные сопутствующие файлы объекта: проверка, контекст XML-определений, нативные потоки и управляемые ими связи по профилю.',
    'owned_form_properties': 'Назначения форм владельца: проверка ссылок и нативных полей.',
    'owned_forms': 'Чтение нативной коллекции форм владельца и определение позиций.',
    'packet_builder': 'Граф помещения, версии, записи объектов и итоговый XML-запрос.',
    'picture_xml': 'Картинки и ссылки на них в формах.',
    'platform_profiles': 'Выбор профиля платформы и структуры выгрузки.',
    'preparation_plan': 'План операции по XML и поиск соседних файлов содержимого.',
    'related_object_changes': 'Изменения связанных существующих объектов при создании.',
    'report_form_properties': 'Специфические свойства управляемых форм отчёта.',
    'rich_text_xml': 'Форматированные строки и их нативное представление.',
    'schema_content': 'Полный XML схемы компоновки данных и нативные потоки СКД.',
    'serialization_context': 'Сопоставление снимка с updateInfo и проверка исходной версии.',
    'serializer_cli': 'Общий JSON-вход Python, ограничения и запись результата.',
    'template_content': 'Преобразование содержимого макета в зависимости от его вида.',
    'template_references': 'Разрешение ссылок в содержимом макетов.',
    'template_serializer': 'Создание и изменение описания и содержимого макета; владельцы выбираются по карте и общим нативным путям.',
    'type_description_xml': 'Описание типов значений метаданных и квалификаторов.',
    'typed_value_xml': 'Типизированные значения свойств формы.',
    'v8unpack_backend': 'Адаптер v8unpack: модели, правила и сборка нативных данных.',
    'xml_namespaces': 'Пространства имён XML и сохранение префиксов QName.',
    'xdto_type_xml': 'QName встроенных, системных и объявленных в каталоге пользовательских XDTO-типов; локальные пространства имён.',
    'xdto_packages': 'Каталог полных XDTO-пакетов: объявления типов, импорты, проверенное содержимое хранилища и целевые файлы.',
    'role_rights_native': 'Чтение и восстановление простых и расширенных нативных таблиц прав; полные матрицы ограничений сохраняются без интерпретации.',
    'role_restrictions_xml': 'Полные условия RLS и шаблоны из Rights.xml: текст, строки для отдельных полей, неявное условие для остальных полей и обратный XML.',
    'metadata_definitions': 'Итоговый индекс UUID и полных XML-имён всех хранимых и вложенных элементов; коллекции читаются из карты схемы без активации сериализаторов.',
    'role_metadata_context': 'Обычные и стандартные ссылки роли и пути RLS: реальные UUID, владелец, признак поля и проверенные отрицательные коды; виртуальным полям не создаются UUID.',
    'role_right_identifiers': 'Проверенный реестр соответствий XML-имён прав и нативных UUID; неизвестные имена и UUID отклоняются.',
    'role_dependencies': 'Добавление неизменённых файлов ролей в план полной конфигурации при замене UUID, на которые ссылаются исходные описатели.',
    'role_rights_xml': 'Преобразование целого Rights.xml в нативный поток: UUID прав, обычные ссылки, условия RLS, шаблоны и флаги; выбор требуемых XML-определений.',
    'metadata_value_list_xml': 'Полный список значений свойства метаданных: ссылки на объекты и строки в раздельных нативных коллекциях.',
    'Вспомогательный': 'Служебные операции протокола и кодирования.',
    'ИдентификаторыМетаданных': 'Доступ OneScript к UUID классов и коллекций.',
    'МенеджерЗапросов': 'Формирование XML-запросов протокола хранилища.',
    'МенеджерХранилищ': 'Операции сервера и управление хранилищами.',
    'ОбработкаXML': 'Разбор ответов сервера, контекста и описаний объектов.',
    'ПравилаПакетовХранилища': 'Правила операций и состава пакетов по классам объектов.',
    'РолиХранилища': 'Роли и права пользователей хранилища.',
    'СериализаторОбъектаХранилища': 'Подготовка JSON для Python и импорт подготовленных пакетов.',
    'СовместимостьПлатформы': 'Проверка поддерживаемого профиля платформы.',
    'ВерсияХранилища': 'Модель версии хранилища.',
    'КлиентХранилища': 'HTTP-вызовы: снимки, захваты, подготовка, помещение и проверки результата.',
    'ОбъектХранилища': 'Описание объекта и проверки допустимости операций.',
    'ОтветСервиса': 'Модель ответа сервера и его ошибок.',
    'ПакетПомещенияОбъекта': 'Модель пакета, его импорт и проверка состава.',
    'ПараметрыСозданияХранилища': 'Параметры создания нового хранилища.',
    'ПользовательХранилища': 'Описание пользователя хранилища.',
    'СнимокОбъектаХранилища': 'Снимок объекта и версия хранилища, на которой он прочитан.',
}

# Public examples describe transformations, not every internal helper.
CONTRACTS = [
    ('metadata_common_xml', 'read', 'Properties как Element + UUID объекта.', '(имя, common): строка и нативная группа общих свойств.'),
    ('metadata_common_xml', 'write', 'Element Properties + нативная группа common.', 'None; свойства добавляются в переданный Element.'),
    ('opaque_owner_references', 'equivalent_roots', 'Исходный и целевой XML владельца, класс, исходный контекст, итоговый индекс имён и необязательное нативное тело.', '(before, after): XML для сравнения с UUID вместо изменённых известных ссылок; при подмене цели, имени или нативного UUID — ошибка. Тела и исходные XML не изменяются.'),
    ('metadata_owner_profiles', 'owner_profiles', 'Нет аргументов; проверенные JSON-профили владельцев форм и непрозрачных контейнеров.', 'Словарь по классу: например ExternalDataSource с путями общих свойств, UUID и коллекций Cube/Table.'),
    ('metadata_owner_change', 'serialize', 'request с полными object_xml/before_xml, классом, UUID, снимком, контекстом и исходной версией; native_content=True во внутренней сборке.', 'ObjectContent с телом и сохранёнными потоками, либо XML-запрос одиночного помещения; неизвестные изменения свойств отклоняются.'),
    ('type_description_xml', 'read', 'Element Type из XML Конфигуратора.', 'Group: например {"Pattern",{"S",64,1}}.'),
    ('type_description_xml', 'export', 'Нативный Pattern + полное XML-имя тега.', 'Element Type с типом и квалификаторами.'),
    ('metadata_object_xml', 'object_xml', 'Полный XML-строка, платформа, класс, индекс ссылок при необходимости.', '(UUID, имя, native_body: bytes, generated_ids: list[str]).'),
    ('metadata_object_xml', 'create', 'Полный XML, платформа, класс; UUID новых форм и макетов, индекс объектов при необходимости.', 'Тот же кортеж; коллекции новых форм и макетов уже включены в тело владельца. Пакета помещения ещё нет.'),
    ('metadata_object_xml', 'change', 'Целевой полный XML, платформа, класс, исходное нативное дерево; контекст и удаления при необходимости.', '(native_body: bytes, feature_ids: list[str]); защищённые части исходного тела проверяются.'),
    ('metadata_object_xml', 'export', 'Нативное дерево, соответствие имён форм UUID, платформа и класс.', 'Element MetaDataObject; для текста нужен ElementTree.tostring. Непредставимые поля не отбрасываются молча.'),
    ('inline_attribute_xml', 'attribute_xml', 'Element Attribute + проверенный нативный шаблон.', '(UUID, имя, нативное дерево встроенного реквизита).'),
    ('tabular_section_xml', 'read', 'Element TabularSection, имя владельца, прежнее тело при изменении, класс владельца.', '(UUID, имя, нативное дерево, UUID признаков, сгенерированные UUID типов).'),
    ('form_definition_xml', 'read', 'XML описания формы, класс владельца и платформа.', '(UUID формы, имя, common). Это описание формы, а не Ext/Form.xml.'),
    ('managed_form_xml', 'convert', 'Прежний нативный поток интерфейса; полный Form.xml, текст модуля и привязки владельца.', 'bytes: полный новый нативный поток управляемой формы.'),
    ('managed_form_operations', 'create_native', 'Класс и имя формы, платформа, нативное дерево владельца; описание, интерфейс, модуль и ссылки.', '(UUID формы, body: bytes, interface: bytes). Описание и интерфейс — разные потоки.'),
    ('v8unpack_backend', 'to_model', 'Нативное дерево Group/Atom.', 'Вложенные list[str] в сыром формате v8unpack; кавычки остаются частью строковых токенов.'),
    ('v8unpack_backend', 'assemble', 'Сырая модель list[str]/вложенных списков, список корневых документов.', 'bytes: нативный текст; не XML Конфигуратора и не пакет хранилища.'),
    ('native_metadata', 'compress', 'bytes нативного содержимого.', 'bytes сжатого содержимого; для обратного преобразования inflate.'),
    ('metadata_context', 'context_objects', 'Base64-строка контекста updateInfo.', 'dict[UUID, documents]; documents = [metadata, permissions, external_map].'),
    ('serialization_context', 'read', 'request со snapshot/context в Base64 + UUID объекта.', 'SnapshotContext: saved, docs, data, context. data — сжатое тело объекта.'),
    ('native_references', 'catalog', 'request с исходным context; внутри общей сборки — каталог итоговых объектов и подготовленных определений.', 'Catalog: итоговая цель, подготовленное или исходное тело; source_files читает исходные тела и потоки одной операцией с проверкой версий, даже при наличии подготовленных целей.'),
    ('metadata_object_xml', 'allocate_creation', 'Полный XML нового объекта, платформа и класс.', 'TypeAllocation: UUID объекта и заранее выделенные UUID типов; декларация доступна до преобразования тел, включая взаимные ссылки.'),
    ('metadata_object_xml', 'reference_dependencies', 'Нативное тело владельца, его профиль и UUID. Например, BasedOn содержит UUID другого документа и UUID самого владельца.', 'dict[UUID, flag]: {UUID другого документа: 0}; самоссылка остаётся в теле, но исключается из зависимостей правилом профиля. Один читатель используется для создания, изменения и сверки прежних ссылок.'),
    ('metadata_type_references', 'resolve', 'Полный XML объекта и request с итоговым каталогом типов или исходным context/snapshots/storage.', 'dict: например cfg:CatalogRef.Товары → UUID ссылочного типа, а не UUID справочника.'),
    ('metadata_type_references', 'reference_definition', 'cfg:CatalogObject.Товары из свойства Source подписки.', '(Catalog, Товары, Object): класс, имя и категория сгенерированного типа; категория Ref имеет другой UUID.'),
    ('metadata_type_sets', 'dependencies', 'Имена {cfg:CatalogObject} и каталог с проверенным снимком или хранилищем версий корня.', '{UUID экземпляра раздела Main текущей конфигурации}; UUID берётся из нативного тела и сверяется с картой внутренних элементов корня.'),
    ('metadata_type_references', 'reconcile', 'Исходное и целевое нативные тела, профиль, исходные связи и полный целевой XML.', 'dict связей: исчезнувшие зависимости проверенных типов и свойств удалены; действующие и непрозрачные связи сохранены.'),
    ('metadata_type_references', 'source_owners', 'Исходное нативное тело, профиль, связи, UUID владельца и проверенные снимки/пакет версии.', 'set UUID: зависимости, подтверждённые сопоставленными свойствами или UUID типов. Создание формы использует этот же источник проверки родителя.'),
    ('external_data', 'extract_many', 'Байты пакета текущей версии и необязательный набор UUID объектов.', 'dict UUID → тело, версии и внешние потоки; индекс и SHA-1 манифест проверяются один раз.'),
    ('external_dependencies', 'validate', 'Исходные объекты, удаления, исчезающие UUID и окончательные тела/потоки изменённых объектов.', 'None либо ошибка до упаковки: сохранённые потоки форм/СКД не могут ссылаться на удаляемые объекты, их типы и значения.'),
    ('type_description_xml', 'read_metadata', 'Element Type и словарь разрешённых ссылок cfg:… → UUID.', 'Общий Pattern скалярного, ссылочного или составного типа; квалификаторы проверяются для каждой ветви.'),
    ('type_description_xml', 'export_metadata', 'Pattern, XML-тег и словарь имён ссылочных типов.', 'Element Type; обратное преобразование проверяется повторным чтением.'),
    ('metadata_object_xml', 'prepare_creation', 'Полный XML нового владельца, платформа, класс, UUID его форм/макетов и итоговый индекс.', 'PreparedCreation: неизменяемое определение со сгенерированными UUID типов, проверяемое при повторном использовании.'),
    ('preparation_plan', 'plan', 'xml_path, context в Base64, options; соседние файлы читаются с диска.', 'dict с operation, kind, object_id, parent_id, object_xml, form_xml, module_text, forms, templates, modules, inline_modules, file_data, removed_ids.'),
    ('object_file_content', 'companion', 'Путь XML, класс и полный текст описания; профили задают имена обязательных файлов в Ext/.', 'dict роль файла → полные байты в Base64; содержимое и пространство имён проверены. Например Package → байты Package.bin.'),
    ('object_file_content', 'convert', 'Класс, XML описания, file_data: роль файла → Base64 и запрос с XML-определениями для файлов со ссылками.', 'dict роль файла → Content(data, relations): нативные байты и контролируемые файлом связи либо None. XDTO переносится побайтно, Rights.xml компилируется целиком.'),
    ('object_file_content', 'definition_context', 'Путь описания, класс, file_data и общий запрос подготовки; для роли доступна иерархическая XML-выгрузка.', 'metadata_definitions: JSON-описания только упомянутых объектов, полей RLS и предков. Полный экспорт передаёт общий итоговый индекс без повторного чтения папки.'),
    ('metadata_value_list_xml', 'read', 'Element списка значений, профиль, индекс объектов и области пространств имён XML.', '(references, strings): UUID выбранных объектов и строковые значения; подписи и ненулевые флажки не поддерживаются.'),
    ('xdto_type_xml', 'read', 'Element QName и его локальные объявления xmlns.', 'Нативное [0, URI, имя] для типа из проверенного каталога; неизвестный тип или несвязанный префикс отклоняется.'),
    ('xdto_packages', 'from_export', 'Папка полной целевой выгрузки и её инвентаризация.', 'Catalog: UUID, пространства имён, объявления типов, импорты и SHA-256 полных файлов Package.bin.'),
    ('xdto_packages', 'from_storage', 'request с context и storage текущей версии в Base64.', 'Catalog только из потоков .0, для которых совпали объект, версия тела и версии всех внешних потоков.'),
    ('role_rights_native', 'read', 'AST нативной таблицы: версия 0 и пары UUID/состояние либо версия 1, число прав, пары и матрицы ограничений.', 'Table: состояния, полные матрицы условий и признак расширенного формата; write восстанавливает AST без потери условий. Это ещё не преобразователь Rights.xml.'),
    ('role_restrictions_xml', 'matrix', 'Полный список restrictionByCondition одного права; resolve_field(name) возвращает нативный путь из контекста метаданных.', 'Матрица {число строк, {1, текст условия, число полей, пути...}, ...}; для ограничений только на поля добавляется строка для остальных полей.'),
    ('role_restrictions_xml', 'templates', 'Полный список restrictionTemplate роли: name и condition из Rights.xml.', 'Нативный список {число шаблонов, {имя, полный текст}, ...}; используется общий кодек переводов строк.'),
    ('metadata_definitions', 'from_inventory', 'Полная инвентаризация целевой XML-выгрузки с узлами, UUID и владельцами хранимых объектов.', 'Index всех хранимых и вложенных элементов: полное имя, реальный UUID, родитель и stored_id тела. Вложенные элементы не выдаются за записи хранилища.'),
    ('role_metadata_context', 'Context.reference', 'Полное XML-имя, например Catalog.Items.Attribute.Text или Catalog.Items.StandardAttribute.Code, и итоговые определения.', 'Обычный заголовок {1, UUID элемента, 0, признак поля}; стандартный — {1, UUID владельца, 1, {-2, UUID класса стандартных полей}, 1}. reference_name проверяет и восстанавливает имя.'),
    ('role_metadata_context', 'Context.definition', 'XML-имя обычного элемента либо стандартного реквизита.', 'Реальное Definition элемента или владельца стандартного поля: отрицательный код и UUID класса не превращаются в фиктивное определение метаданных.'),
    ('role_metadata_context', 'Context.field_path', 'Владелец и обычное, стандартное или вложенное поле табличной части: Catalog.Items / Code либо Rows.Amount.', 'Обычный путь {{0},{0,UUID поля}}, стандартный {{0},{-2}}, вложенный {{0,UUID табличной части},{0,UUID реквизита}}. Проверяются полный путь владения, класс и реальные UUID.'),
    ('role_right_identifiers', 'right_id', 'XML-имя права, например ThinClient.', 'Проверенный UUID 3c00c6ee-844e-4620-85e4-671e72f114d9; right_name выполняет обратное преобразование. Неизвестное право вызывает ошибку.'),
    ('role_dependencies', 'expand', 'План полной конфигурации, итоговый XML-инвентарь, исходные описатели и каталоги выгрузок.', 'Дополнительные операции изменения ролей, ссылающихся на исчезнувшие UUID; changed_files пуст, reason=metadata_reference_changed. Их целый Rights.xml пересобирается обычным путём без записи правок в XML.'),
    ('role_rights_xml', 'compile', 'Полный Ext/Rights.xml и Context итоговых XML-определений: объекты, права, ограничения, шаблоны и три флага.', 'Нативный поток версии 10: обычные и 61 стандартная ссылка, 59 стандартных полей RLS и реквизиты табличной части по пути Rows.Amount. Номер строки табличной части и более глубокие пути пока не подключены.'),
    ('role_rights_native', 'file_references', 'Полные байты нативного потока прав роли.', 'UUID объектов и обычных полей RLS для связей и защиты удаления. Стандартное поле зависит от UUID владельца; отрицательные коды, UUID класса и UUID в запросах не становятся метаданными.'),
    ('xml_namespaces', 'serialize', 'Element полного XML или фрагмента, включая буквальные CR в текстовых значениях.', 'Строка XML с CR как &#13;. При переписывании дерева с текстовыми QName используется render с областями пространств имён.'),
    ('xml_namespaces', 'parse', 'Полный XML-текст.', '(Element, dict Element → действующие объявления xmlns): локальные переопределения префиксов сохраняются.'),
    ('configuration_export', 'plan', 'directory, baseline_directory и context в Base64.', 'dict: operations, removed_ids, new_ids, xml_paths, отпечатки файлов и счётчики.'),
    ('configuration_commit', 'prepare', 'Полная целевая и исходная выгрузки, context и platform.', '(plan, changes): план с snapshot_ids/needs_storage и подготовленные изменения.'),
    ('object_creation_serializer', 'serialize', 'request: object_type задаёт класс, object_xml — полный XML; context и snapshots описывают текущее хранилище.', 'dict: request_xml, data в Base64, object_id, descriptions, externals и сведения об исходных объектах.'),
    ('object_change_serializer', 'serialize', 'request: полный object_xml, snapshot/context в Base64, UUID, исходная версия и класс.', 'Обычно dict(request_xml, external_owners). При native_content=True: ObjectContent(docs, body, streams, externals).'),
    ('configuration_serializer', 'serialize', 'request с XML корня и актуальными snapshot/context.', '(request_xml: str, native_body: bytes). JSON CLI возвращает только request_xml.'),
    ('managed_form_operations', 'create', 'request: снимок/контекст владельца, имя и файлы новой формы.', 'dict: data в Base64, object_id, descriptions, externals; включает новую форму и изменение владельца.'),
    ('managed_form_operations', 'change', 'request: snapshot, context и пакет версии storage в Base64; definition_xml, form_xml, module_text.', 'dict: data в Base64, object_id, class_id, original, local, external_name, external_version.'),
    ('managed_form_operations', 'compile_change', 'Тот же request и необязательное итоговое тело владельца.', 'ObjectContent: docs, body, streams, externals; версии самого объекта ещё не изменены, пакет не собирается.'),
    ('commonmodule_serializer', 'compile_change', 'request: полный object_xml, source_text и проверенные snapshot/context.', 'ObjectContent с нативным телом модуля и заменённым внешним текстом; пакет не собирается.'),
    ('template_serializer', 'compile_change', 'request: definition_xml, содержимое макета, snapshot/context и storage.', 'ObjectContent с описанием и полным внешним потоком макета; пакет не собирается.'),
    ('template_serializer', 'create', 'request: снимок и контекст владельца, definition_xml и содержимое макета; storage для ссылок СКД.', 'Одиночный пакет или, при contents_only=True, CreationContent с одним новым ObjectContent без промежуточной упаковки.'),
    ('managed_form_operations', 'serialize', 'request с обязательным operation: Создание или Изменение; остальные поля зависят от операции.', 'Результат create или change. Это общий вход JSON CLI, без определения операции по косвенным признакам.'),
    ('delete_object_serializer', 'serialize', 'request с UUID удаления, снимками объекта/родителя и полным целевым XML родителя.', 'dict: data в Base64, object_id, parent_id, removed_ids, descriptions, externals.'),
    ('configuration_commit', 'serialize', 'Полные выгрузки и контекст; snapshots по плану, storage при необходимости; версии и платформа.', 'dict: data, descriptions, requested, changed_ids, new_ids, removed_ids, externals и версии хранилища.'),
    ('packet_builder', 'assemble', 'Нативный граф помещения и ObjectRecord: UUID, metadata, сжатое body, внешние потоки.', 'bytes готового двоичного пакета помещения. Для JSON используется Base64.'),
    ('serializer_cli', 'run', 'handler + пути входного и выходного JSON в argv.', 'Выходной файл: {ok: true, ...результат} либо {ok: false, error: ...}.'),
]


def transformation_examples():
    return r'''## Примеры преобразований

Примеры 1–4 исполняются последовательно из корня репозитория и проверяются тестом.
Они не обращаются к серверу и ничего не помещают в хранилище. Полные сигнатуры
и типы результатов приведены в таблице контрактов ниже.

### 1. XML свойства → нативные общие свойства

```python
from pathlib import Path
import sys
from xml.etree import ElementTree as E
sys.path.insert(0, str(Path("src/Сериализация").resolve()))
import metadata_common_xml as common
import metadata_object_xml as objects
import native_metadata as native
import type_description_xml as types
import v8unpack_backend as backend

oid = "11111111-1111-4111-8111-111111111111"
props = E.fromstring(''' + "'''" + r'''
<Properties xmlns="http://v8.1c.ru/8.3/MDClasses">
  <Name>Products</Name><Comment>before</Comment>
</Properties>
''' + "'''" + r''')
name, group = common.read(props, oid)
assert name == "Products"
assert native.render(group) == (
    '{3,{1,0,11111111-1111-4111-8111-111111111111},'
    '"Products",{0},"before",0,0,00000000-0000-0000-0000-000000000000,0}'
)
```

Вход — Element с Name и Comment. Выход — имя и `Group`, а не XML-строка.
`native.render(group)` показывает эту группу в нативной записи 1С.

### 2. XML типа → Pattern → модель v8unpack → нативный текст

```python
type_xml = E.fromstring(''' + "'''" + r'''
<Type xmlns="http://v8.1c.ru/8.3/MDClasses"
      xmlns:v8="http://v8.1c.ru/8.1/data/core">
  <v8:Type>xs:string</v8:Type>
  <v8:StringQualifiers>
    <v8:Length>64</v8:Length><v8:AllowedLength>Variable</v8:AllowedLength>
  </v8:StringQualifiers>
</Type>
''' + "'''" + r''')
pattern = types.read(type_xml)
assert native.render(pattern) == '{"Pattern",{"S",64,1}}'

model = backend.to_model(pattern)
assert model == ['"Pattern"', ['"S"', '64', '1']]
# assemble принимает список документов, поэтому модель обёрнута ещё в один список.
raw_pattern = backend.assemble([model])
assert native.render(native.Parser(raw_pattern.decode("utf-8-sig")).documents()[0]) == native.render(pattern)
assert native.inflate(native.compress(raw_pattern)) == raw_pattern
```

Здесь видна граница v8unpack: XML сначала преобразуется нашими правилами в
нативное дерево, затем адаптер передаёт сырую модель для сборки текста.
`64` в модели — строковый токен, а не Python int; кавычки вокруг строковых
значений тоже сохраняются в токенах.

### 3. Полный XML справочника → нативное тело

```python
xml_before = ''' + "'''" + r'''
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" version="2.21">
  <Catalog uuid="11111111-1111-4111-8111-111111111111">
    <Properties><Name>Products</Name><Comment>before</Comment></Properties>
    <ChildObjects/>
  </Catalog>
</MetaDataObject>
''' + "'''" + r'''
object_id, object_name, raw_body, generated_ids = objects.create(
    xml_before, "8.5.1.1529", "Catalog"
)
assert (object_id, object_name) == (oid, "Products")
assert isinstance(raw_body, bytes)
assert len(generated_ids) == 10
assert len(set(generated_ids)) == 10
source = native.Parser(raw_body.decode("utf-8-sig")).documents()[0]
assert native.val(source[1][9][1][4]) == "before"
```

Выход — `(UUID, имя, bytes, список UUID)`. В примере отсутствует InternalInfo,
поэтому создаются десять новых UUID типов; их значения меняются при каждом запуске.
При переданном InternalInfo используются UUID из XML. `raw_body` — только
несжатое тело справочника: в нём ещё нет описания версии, графа помещения или HTTP.
Путь `[1][9][1][4]` здесь показан для проверенного профиля Catalog; общий код берёт
пути из профилей, не предполагая одинаковой структуры у всех классов.

### 4. Изменение полного XML → новое тело → обратная выгрузка

```python
xml_after = xml_before.replace("before", "after")
changed_body, feature_ids = objects.change(
    xml_after, "8.5.1.1529", "Catalog", source
)
changed = native.Parser(changed_body.decode("utf-8-sig")).documents()[0]
assert native.val(changed[1][9][1][4]) == "after"
assert feature_ids == []  # Встроенных реквизитов/табличных частей в примере нет.

tree = objects.export(changed, {}, "8.5.1.1529", "Catalog")
exported_xml = E.tostring(tree, encoding="unicode")
assert tree[0].get("uuid") == oid
assert tree[0].find(common.Q + "Properties/" + common.Q + "Comment").text == "after"
assert tree[0].find(common.Q + "InternalInfo") is not None
assert objects.create(exported_xml, "8.5.1.1529", "Catalog")[2] == changed_body
```

Для проверки изменения передаётся исходное нативное дерево. Если InternalInfo
в целевом XML отсутствует, прежние UUID типов сохраняются. `{}` при export —
пустое соответствие имён форм UUID. Выход export — Element, поэтому для файла
нужен tostring. Константы используют тот же механизм создания с kind="Constant";
помещение изменения существующей константы пока не объявлено поддержанным.

### 5. Файлы выгрузки → план подготовки

Схема вызова для реальной выгрузки и контекста сервера, не автономный пример:

```text
preparation_plan.plan({
  "xml_path": "C:/export/Catalogs/Products.xml",
  "context": "<Base64 updateInfo>",
  "options": {}
})
  ↓ dict
operation: "Создание" или "Изменение" — определяется по UUID и контексту
kind: "Catalog"
object_id: UUID из Products.xml
parent_id: UUID конфигурации
object_xml: полный текст Products.xml
forms: найденные файлы новых форм при создании владельца
modules / inline_modules: найденные полные тексты модулей
removed_ids: UUID отсутствующих отдельно хранимых детей при изменении
```

Если передан XML описания формы, план отдельно читает соседние Ext/Form.xml и
Ext/Form/Module.bsl; они попадают в form_xml и module_text. Сам план не содержит
готового нативного тела или пакета помещения.

### 6. Полная управляемая форма → два нативных потока

```text
managed_form_operations.create_native(
  kind="Catalog", name="ItemForm", platform="8.5.1.1529",
  owner=<нативное дерево справочника>,
  definition_xml=<текст Forms/ItemForm.xml>,
  interface_xml=<весь Forms/ItemForm/Ext/Form.xml>,
  module_text=<весь Forms/ItemForm/Ext/Form/Module.bsl>,
  references=<разрешённые ссылки на типы метаданных>
)
  ↓ tuple
(form_uuid, body_bytes, interface_bytes)
```

body_bytes описывает объект формы, interface_bytes содержит интерфейс и текст
её модуля. При изменении managed_form_xml.convert получает прежний нативный поток
и возвращает новый полный поток. Обработчики managed_form_operations.create и
managed_form_operations.change дополнительно собирают пакет, используя снимки,
контекст и при необходимости пакет текущей версии. Для полной папки используется
compile_change: результат ObjectContent содержит docs, body, streams, externals
без промежуточного пакета. Создание с contents_only=True возвращает
CreationContent(objects, version_code), где objects сопоставляет UUID с
ObjectContent. Общий JSON-вход serialize
выбирает обработчик по operation="Создание" или operation="Изменение".
create_native этого не делает. Добавление отдельного поля по attribute_name
не поддерживается: для изменения интерфейса нужен полный Form.xml.

### 7. Нативные тела → пакет → JSON-мост → HTTP

```text
packet_builder.assemble(
  graph=<нативный граф помещения>,
  objects=[ObjectRecord(
    object_id=<UUID>, metadata=<нативное описание, bytes>,
    body=<сжатое тело, bytes>, externals=<внешние потоки>
  )]
)
  ↓ bytes двоичного пакета
Base64 для поля data в JSON
  ↓
СериализаторОбъектаХранилища: ПакетПомещенияОбъекта
  ↓ только при вызове КлиентХранилища.ПоместитьПакет
HTTP-запрос к серверу хранилища и проверка результата
```

Нельзя передать raw_body из примера 3 вместо пакета: assemble требует ещё граф
помещения и описания объектов. Одни сериализаторы возвращают data и descriptions,
другие request_xml, из которого OneScript извлекает данные пакета. Поэтому
результаты разных сериализаторов нельзя считать одинаковыми словарями.

Обёртка JSON CLI добавляет ok к результату обработчика. Например:

```json
{"ok": true, "request_xml": "<XML запроса, содержащий Base64 пакета>"}
```

При ошибке проверки входа:

```json
{"ok": false, "error": "описание ошибки"}
```

Это формат файлового моста Python, не ответ HTTP-сервера хранилища.
Вызов функции serialize напрямую не добавляет поле ok.
'''


def inventory(root=ROOT):
    modules = {}
    for path in sorted((root / 'src' / 'Сериализация').glob('*.py')):
        modules['python:' + path.stem] = dict(
            name=path.stem, language='Python', path=path.relative_to(root).as_posix())
    for path in sorted([*(root / 'src' / 'Классы').glob('*.os'),
                        *(root / 'src' / 'Модули').glob('*.os')]):
        modules['onescript:' + path.stem] = dict(
            name=path.stem, language='OneScript', path=path.relative_to(root).as_posix())
    for module in modules.values():
        if module['name'] not in PURPOSES:
            raise ValueError('Describe new module: ' + module['name'])
        module['purpose'] = PURPOSES[module['name']]
    return modules


def dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = dotted(node.value)
        return parent + '.' + node.attr if parent else None
    return None


def extract(root=ROOT):
    modules = inventory(root)
    imports, calls = set(), {}

    def call(caller, callee, function):
        if callee in modules and caller != callee:
            calls.setdefault((caller, callee), set()).add(function)

    aliases = {entry.get('name'): 'onescript:' + Path(entry.get('file')).stem
               for entry in E.parse(root / 'lib.config').getroot()}
    for key, module in modules.items():
        text = (root / module['path']).read_text(encoding='utf-8-sig')
        if module['language'] == 'Python':
            tree = ast.parse(text)
            bindings = {}
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        target = 'python:' + alias.name
                        if target in modules:
                            bindings[alias.asname or alias.name] = (target, '')
                            imports.add((key, target))
                elif isinstance(node, ast.ImportFrom):
                    target = 'python:' + str(node.module)
                    if target in modules:
                        imports.add((key, target))
                        for alias in node.names:
                            bindings[alias.asname or alias.name] = (target, alias.name)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    name = dotted(node.func)
                    if name and name.split('.')[0] in bindings:
                        target, prefix = bindings[name.split('.')[0]]
                        suffix = name.partition('.')[2]
                        call(key, target, '.'.join(part for part in (prefix, suffix) if part))
        else:
            # Strip comments and string literals before finding named module calls.
            code = re.sub(r'//[^\r\n]*|"(?:""|[^"])*"', ' ', text)
            for name, function in re.findall(r'([\wА-Яа-яЁё]+)\.([\wА-Яа-яЁё]+)\s*\(', code):
                if name in aliases:
                    call(key, aliases[name], function)
            for name in re.findall(r'Новый\s+([\wА-Яа-яЁё]+)', code):
                if name in aliases:
                    call(key, aliases[name], 'ПриСозданииОбъекта')
            for script in re.findall(r'"([a-z_]+)\.py"', text):
                call(key, 'python:' + script, 'JSON CLI')
    contracts = []
    for name, function, inputs, outputs in CONTRACTS:
        path = root / modules['python:' + name]['path']
        scopes = [ast.parse(path.read_text(encoding='utf-8-sig'))]
        for part in function.split('.'):
            scopes = [node for scope in scopes for node in scope.body
                      if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == part]
        matches = [node for node in scopes if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        if len(matches) != 1:
            raise ValueError('Example function is missing: ' + name + '.' + function)
        contracts.append(dict(module='python:' + name, function=function,
                              signature=function + '(' + ast.unparse(matches[0].args) + ')',
                              inputs=inputs, outputs=outputs))
    return dict(modules=modules, contracts=contracts,
                imports=[dict(caller=a, callee=b) for a, b in sorted(imports)],
                calls=[dict(caller=a, callee=b, functions=sorted(names))
                       for (a, b), names in sorted(calls.items())])


def markdown(data):
    modules = data['modules']
    incoming = {key: set() for key in modules}
    outgoing = {key: set() for key in modules}
    for edge in data['calls']:
        incoming[edge['callee']].add(edge['caller'])
        outgoing[edge['caller']].add(edge['callee'])

    def names(keys):
        return ', '.join('`' + modules[key]['name'] + '`' for key in sorted(keys)) or '—'

    lines = ['# Карта модулей', '',
             'Файл формируется `tools/build_module_map.py`. Назначения модулей описаны в инструменте; '
             'связи извлекаются из текущих исходников. Проверка актуальности: '
             '`python tools/build_module_map.py --check`.', '',
             'Таблицы показывают прямые вызовы между модулями производственного кода. '
             'В [машинной карте](module-map.json) перечислены вызываемые функции и отдельно импорты. '
             'Импорт сам по себе не означает вызов. Тесты, внешние библиотеки и файлы профилей JSON '
             'в таблицы модулей не включены.', '',
             'Это статическая карта: вызовы через параметры, возвращённые объекты, динамические '
             'импорты и методы экземпляров полностью не разрешаются. Для OneScript учитываются '
             'имена из lib.config, конструкторы и имена Python-файлов в мосте; ссылки в комментариях '
             'и вызовы HTTP не считаются локальными вызовами модулей.', '',
             '## Основные пути', '', '```mermaid', 'flowchart TD',
             '    Client[КлиентХранилища] --> HTTP[МенеджерЗапросов и ОбработкаXML]',
             '    Client --> Bridge[СериализаторОбъектаХранилища]',
             '    Bridge --> Plan[preparation_plan / configuration_export]',
             '    Bridge --> Commit[configuration_commit: полная выгрузка]',
             '    Bridge --> Create[object_creation_serializer: создание]',
             '    Bridge --> Change[object_change_serializer: изменение]',
             '    Bridge --> Root[configuration_serializer: корень]',
             '    Bridge --> Forms[managed_form_operations: создание и изменение]',
             '    Bridge --> Delete[delete_object_serializer / automatic_deletion]',
             '    Commit --> Create', '    Commit --> Change', '    Commit --> Forms',
             '    Create --> Content[native_content: ObjectContent / CreationContent]',
             '    Change --> Content', '    Forms --> Content', '    Content --> Commit',
             '    Commit --> Packet[packet_builder: конечный пакет]',
             '    Create --> XML[metadata_object_xml: полный XML объекта]',
             '    Change --> XML', '    Root --> RootXML[configuration_xml]',
             '    Forms --> FormXML[managed_form_xml]',
             '    XML --> Common[metadata_common_xml: общие свойства]',
             '    XML --> Inline[inline_object_xml / tabular_section_xml]',
             '    Inline --> Attribute[inline_attribute_xml]',
             '    Attribute --> Common',
             '    XML --> Native[native_metadata]', '    RootXML --> Native',
             '    FormXML --> Native', '    Create --> Packet[packet_builder]',
             '    Change --> Packet', '    Root --> Packet', '    Packet --> Native',
             '    FormXML --> Elements[managed_form_elements]',
             '    FormXML --> Rules[managed_form_rules]',
             '    FormXML --> Backend[v8unpack_backend: адаптер]',
             '    Elements --> Backend', '    Rules --> Backend',
             '    Native --> Backend',
             '    Backend --> V8[v8unpack: модели и сборка нативного текста]',
             '    Rules -. calc_offset .-> V8',
             '```', '',
             'Схема показывает основные этапы. Точный список прямых связей приведён ниже; '
             'пакет проходит через JSON-мост обратно в OneScript, после чего клиент отправляет '
             'его по HTTP. Подготовка пакета сама по себе не выполняет помещение.', '',
             '`v8unpack_backend` использует модели v8unpack для разбора и сборки формы, '
             'определяет позиции полей элементов и собирает нативный текст. '
             '`managed_form_rules` также напрямую использует `v8unpack.helper.calc_offset`. '
             'Сопоставление XML Конфигуратора с этими моделями, привязки данных, контекст '
             'хранилища и пакеты помещения реализованы в наших модулях.', '',
             '## Границы ответственности', '',
             '- `native_metadata` не читает XML и не собирает операции помещения.',
             '- `metadata_context` читает updateInfo; `serialization_context` сопоставляет его со снимком.',
             '- XML-преобразователи возвращают нативное содержимое; сериализаторы операций собирают пакеты.',
             '- `configuration_commit` координирует итоговую конфигурацию и связанные изменения.',
             '- HTTP, захваты и подтверждение помещения принадлежат клиенту OneScript.', '']
    lines += transformation_examples().splitlines() + ['', '## Контракты основных функций', '',
              'Сигнатуры извлекаются из исходников при построении карты. '
              'Group/Atom — нативное дерево; Element — узел XML; bytes — двоичные данные; '
              'Base64 — строка для JSON-моста. Кортежи перечислены в порядке возвращаемых значений.', '',
              '| Функция | Что подаётся на вход | Что возвращается |',
              '| --- | --- | --- |']
    for contract in data['contracts']:
        name = modules[contract['module']]['name']
        lines.append('| `' + name + '.' + contract['signature'] + '` | '
                     + contract['inputs'] + ' | ' + contract['outputs'] + ' |')
    lines.append('')
    for language in ['OneScript', 'Python']:
        lines += ['## ' + language, '', '| Модуль | Ответственность | Кто вызывает | Что вызывает |',
                  '| --- | --- | --- | --- |']
        for key, module in sorted(modules.items()):
            if module['language'] != language:
                continue
            link = '[' + module['name'] + '](../' + module['path'] + ')'
            lines.append('| ' + ' | '.join([link, module['purpose'], names(incoming[key]),
                                            names(outgoing[key])]) + ' |')
        lines.append('')
    lines += ['## Профили и внешние зависимости', '',
              'JSON-файлы рядом с Python-модулями содержат проверенные нативные шаблоны, '
              'позиции свойств, UUID, правила коллекций, владельцев и элементов форм. '
              'Их загружают модули профилей и соответствующие преобразователи. '
              '`v8unpack_backend` адаптирует установленный v8unpack; конвертеры XML '
              'и клиент хранилища остаются частью этой библиотеки.', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    data = extract()
    outputs = {
        ROOT / 'docs' / 'module-map.json': json.dumps(data, ensure_ascii=False, indent=2) + '\n',
        ROOT / 'docs' / 'module-map.md': markdown(data),
    }
    for path, text in outputs.items():
        if args.check:
            if not path.is_file() or path.read_text(encoding='utf-8-sig') != text:
                raise SystemExit('Module map is out of date: ' + str(path))
        else:
            path.write_bytes(text.replace('\n', '\r\n').encode('utf-8'))
    print('Module map: ' + str(len(data['modules'])) + ' modules, '
          + str(len(data['calls'])) + ' call edges.')


if __name__ == '__main__':
    main()
