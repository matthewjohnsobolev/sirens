import re
from dataclasses import dataclass

ALERT_TEMPLATE = (
    "🔴 {time} Повітряна тривога в {districts}\nСлідкуйте за подальшими повідомленнями.\n{hashtags}"
)

ALERT_CANCELLATION_TEMPLATE = (
    "🟢 {time} Відбій тривоги в {districts}\nСлідкуйте за подальшими повідомленнями.\n{hashtags}"
)

PARTIAL_CANCELLATION_TEMPLATE = (
    "🟡 {time} Відбій тривоги в {districts}\n{notice}\n{ongoing}\n{hashtags}"
)

ONGOING_NOTICE = "Зверніть увагу, тривога ще триває у:"


_HASHTAG_DROPPED = re.compile(r"[.'’]")
_HASHTAG_UNDERSCORED = re.compile(r"[\s-]+")


def _hashtag(place: str) -> str:
    return "#" + _HASHTAG_UNDERSCORED.sub("_", _HASHTAG_DROPPED.sub("", place))


def _districts_block(districts: tuple[str, ...], end: str = "") -> str:
    if len(districts) == 1:
        return districts[0] + end
    return "\n" + "\n".join(f"• {place}" for place in districts)


def _render(template: str, time: str, districts: tuple[str, ...], end: str = "") -> str:
    return template.format(
        time=time,
        districts=_districts_block(districts, end),
        hashtags=" ".join(_hashtag(place) for place in districts),
    )


def oblast_message(oblast_name: str, time: str = "12:00") -> str:
    """A post naming the oblast instead of listing its districts."""
    return _render(ALERT_TEMPLATE, time, (oblast_name,))


@dataclass(frozen=True)
class AlertSample:
    regions: tuple[str, ...]

    districts: tuple[str, ...]

    alert_time: str = "12:00"
    cancellation_time: str = "13:00"

    @property
    def id(self) -> str:
        suffix = "-combined" if len(self.districts) > 1 else ""
        return "-".join(self.regions) + suffix

    @property
    def alert_message(self) -> str:
        return self._render(ALERT_TEMPLATE, self.alert_time)

    @property
    def cancellation_message(self) -> str:
        return self._render(ALERT_CANCELLATION_TEMPLATE, self.cancellation_time, end=".")

    def _render(self, template: str, time: str, end: str = "") -> str:
        return _render(template, time, self.districts, end)


@dataclass(frozen=True)
class MapOnlySample:
    """A post naming districts I do not broadcast to.

    `districts` are the place names in the post. `recorded` are the district
    keys whose map state must change, and none of them may reach a channel;
    `broadcast` names the keys in the same post that must still be aired, so a
    mixed post proves the two halves of the parser do not shadow each other.
    """

    id: str

    districts: tuple[str, ...]

    recorded: tuple[str, ...]

    broadcast: tuple[str, ...] = ()

    alert_time: str = "12:00"
    cancellation_time: str = "13:00"

    @property
    def alert_message(self) -> str:
        return _render(ALERT_TEMPLATE, self.alert_time, self.districts)

    @property
    def cancellation_message(self) -> str:
        return _render(ALERT_CANCELLATION_TEMPLATE, self.cancellation_time, self.districts, ".")


@dataclass(frozen=True)
class PartialCancellationSample:
    """A post clearing one place while the alert runs on elsewhere.

    `districts` are the places cleared, and their channels — `regions` — must
    hear the cancellation. `ongoing` is the trailing note listing where the
    alert is still running; it announces nothing, so the channels whose
    triggers it happens to contain — `silenced` — must hear nothing at all.
    """

    id: str

    districts: tuple[str, ...]

    ongoing: tuple[str, ...]

    regions: tuple[str, ...] = ()

    silenced: tuple[str, ...] = ()

    time: str = "08:01"

    @property
    def message(self) -> str:
        return PARTIAL_CANCELLATION_TEMPLATE.format(
            time=self.time,
            districts=_districts_block(self.districts, "."),
            notice=ONGOING_NOTICE,
            ongoing="\n".join(f"- {place}" for place in self.ongoing),
            hashtags=" ".join(_hashtag(place) for place in self.districts),
        )


def region_sample(region, district, alert_time="12:00", cancellation_time="13:00"):
    """A post about a single district — the common case."""
    return AlertSample((region,), (district,), alert_time, cancellation_time)


MESSAGES_SAMPLES = (
    region_sample("kyiv", "м. Київ", "04:31", "05:24"),
    region_sample("cherkasy", "Черкаський район", "10:08", "11:06"),
    region_sample("uman", "Уманський район", "19:53", "21:11"),
    region_sample("zvenyhorodka", "Звенигородський район", "17:44", "18:49"),
    region_sample("zolotonosha", "Золотоніський район", "17:17", "18:04"),
    region_sample("chernihiv", "Чернігівський район", "23:47", "00:29"),
    region_sample("kropyvnytskyi", "Кропивницький район", "06:59", "07:42"),
    region_sample("poltava", "Полтавський район", "13:10", "14:41"),
    region_sample("kremenchuk", "Кременчуцький район", "12:57", "14:34"),
    region_sample("vinnytsia", "Вінницький район", "14:34", "16:26"),
    region_sample("zhytomyr", "Житомирський район", "12:44", "13:56"),
    region_sample("bilatserkva", "Білоцерківський район", "20:26", "21:56"),
    region_sample("bucha", "Бучанський район", "19:53", "20:59"),
    region_sample("fastiv", "Фастівський район", "19:27", "21:02"),
    region_sample("kharkiv", "м. Харків", "22:42", "23:18"),
    region_sample("sumy", "Сумський район", "06:12", "06:55"),
    region_sample("zaporizhzhia", "м. Запоріжжя", "18:07", "18:47"),
    region_sample("dnipro", "Дніпровський район", "00:21", "01:29"),
    region_sample("kryvyirih", "Криворізький район", "05:03", "06:46"),
    region_sample("kamianske", "Кам'янський район", "03:26", "04:53"),
    region_sample("nikopol", "Нікопольський район", "10:27", "11:30"),
    region_sample("kherson", "Херсонський район", "08:44", "09:18"),
    region_sample("mykolaiv", "Миколаївський район", "23:33", "01:21"),
    region_sample("pervomaisk", "Первомайський район", "09:11", "10:07"),
    region_sample("odesa", "Одеський район", "02:16", "03:20"),
    region_sample("izmail", "Ізмаїльський район", "20:17", "21:55"),
    region_sample("lviv", "Львівський район", "04:28", "05:45"),
    region_sample("lutsk", "Луцький район", "18:28", "19:59"),
    region_sample("kovel", "Ковельський район", "20:11", "22:10"),
    region_sample("rivne", "Рівненський район", "16:12", "17:44"),
    region_sample("ternopil", "Тернопільський район", "02:19", "03:52"),
    region_sample("khmelnytskyi", "Хмельницький район", "15:59", "16:56"),
    region_sample("ivanofrankivsk", "Івано-Франківський район", "11:29", "12:08"),
    region_sample("uzhhorod", "Ужгородський район", "15:36", "17:26"),
    region_sample("chernivtsi", "Чернівецький район", "11:32", "12:50"),
)

COMBINED_SAMPLES = (
    AlertSample(
        regions=("ivanofrankivsk",),
        districts=(
            "Івано-Франківський район",
            "Коломийський район",
            "Надвірнянський район",
            "Калуський район",
            "Верховинський район",
        ),
        alert_time="15:59",
        cancellation_time="16:56",
    ),
    AlertSample(
        regions=("dnipro", "kryvyirih", "kamianske", "nikopol"),
        districts=(
            "Дніпровський район",
            "Криворізький район",
            "Кам'янський район",
            "Нікопольський район",
            "Синельниківський район",
        ),
        alert_time="00:21",
        cancellation_time="01:29",
    ),
    AlertSample(
        regions=("kyiv", "bilatserkva", "bucha", "fastiv"),
        districts=(
            "м. Київ",
            "Білоцерківський район",
            "Бучанський район",
            "Фастівський район",
        ),
        alert_time="04:31",
        cancellation_time="05:24",
    ),
)

ALL_SAMPLES = MESSAGES_SAMPLES + COMBINED_SAMPLES

# Alerts are cleared per hromada, so a district's channels can hear an all-clear
# for one town while the district around it is still under alert. The source
# says so in a trailing note, which names places the post is *not* clearing.
PARTIAL_CANCELLATION_SAMPLES = (
    PartialCancellationSample(
        id="nikopol-city-cleared-while-oblast-runs-on",
        districts=("м. Нікополь та Нікопольська територіальна громада",),
        ongoing=("Дніпропетровська область", "Нікопольський район"),
        regions=("nikopol",),
        silenced=("dnipro", "kryvyirih", "kamianske"),
        time="08:01",
    ),
    PartialCancellationSample(
        id="hromada-without-a-channel-clears-nobody",
        districts=("м. Марганець та Марганецька міська територіальна громада",),
        ongoing=("Дніпропетровська область", "Нікопольський район"),
        silenced=("dnipro", "kryvyirih", "kamianske", "nikopol"),
        time="09:14",
    ),
    PartialCancellationSample(
        id="two-districts-cleared-third-runs-on",
        districts=("Бучанський район", "Фастівський район"),
        ongoing=("Київська область", "Білоцерківський район"),
        regions=("bucha", "fastiv"),
        silenced=("bilatserkva",),
        time="21:37",
    ),
)


MAP_ONLY_SAMPLES = (
    MapOnlySample(
        id="vyshhorod",
        districts=("Вишгородський район",),
        recorded=("vyshhorod",),
        alert_time="03:12",
        cancellation_time="04:40",
    ),
    MapOnlySample(
        id="synelnykove",
        districts=("Синельниківський район",),
        recorded=("synelnykove",),
        alert_time="22:05",
        cancellation_time="23:31",
    ),
    MapOnlySample(
        id="lubny",
        districts=("Лубенський район",),
        recorded=("lubny",),
        alert_time="07:48",
        cancellation_time="08:22",
    ),
    MapOnlySample(
        id="zviahel-under-its-former-name",
        districts=("Новоград-Волинський район",),
        recorded=("zviahel",),
        alert_time="13:03",
        cancellation_time="14:17",
    ),
    MapOnlySample(
        id="kupiansk-with-a-curly-apostrophe",
        districts=("Куп\u2019янський район",),
        recorded=("kupiansk",),
        alert_time="05:26",
        cancellation_time="06:09",
    ),
    MapOnlySample(
        id="kupiansk-with-a-straight-apostrophe",
        districts=("Куп'янський район",),
        recorded=("kupiansk",),
        alert_time="05:26",
        cancellation_time="06:09",
    ),
    MapOnlySample(
        id="kamianets-podilskyi-does-not-raise-podilsk",
        districts=("Кам'янець-Подільський район",),
        recorded=("kamianetspodilskyi",),
        alert_time="16:41",
        cancellation_time="17:55",
    ),
    MapOnlySample(
        id="bilhorod-dnistrovskyi-does-not-raise-dnistrovskyi",
        districts=("Білгород-Дністровський район",),
        recorded=("bilhoroddnistrovskyi",),
        alert_time="01:14",
        cancellation_time="02:38",
    ),
    MapOnlySample(
        id="mixed-broadcast-and-map-only",
        districts=("Бучанський район", "Вишгородський район"),
        recorded=("vyshhorod",),
        broadcast=("bucha",),
        alert_time="19:53",
        cancellation_time="20:59",
    ),
)
