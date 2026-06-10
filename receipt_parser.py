import re
import json
from typing import Any, Dict, List, Optional

from ocr_linebyline import build_line_result


# --------------------------날짜-------------------------------------------

DATE_PATTERNS = [
    r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})",
    r"(\d{2})[-./](\d{1,2})[-./](\d{1,2})",
]


def _is_valid_date_parts(year: str, month: str, day: str) -> bool:
    m = int(month)
    d = int(day)

    if len(year) not in (2, 4):
        return False
    if not (1 <= m <= 12):
        return False
    if not (1 <= d <= 31):
        return False

    return True


PHONE_PATTERN = r"(?:\d{2,4}[-.\s]?\d{3,4}[-.\s]?\d{4})"
BIZNO_PATTERN = r"(?:\d{3}[-.\s]?\d{2}[-.\s]?\d{5})"


def _looks_like_phone(text: str) -> bool:
    return re.search(PHONE_PATTERN, text) is not None


def _looks_like_bizno(text: str) -> bool:
    return re.search(BIZNO_PATTERN, text) is not None


def _find_valid_date(text: str, patterns: List[str]) -> Optional[str]:
    normalized = text

    # 날짜 바로 뒤에 시간이 숫자로 붙은 경우
    normalized = re.sub(
        r"(\d{2,4}[-./]\d{1,2}[-./]\d{1,2})(\d{1,2}:\d{2}(?::\d{2})?)",
        r"\1 \2",
        normalized
    )

    # 날짜 바로 뒤에 오전/오후가 붙은 경우
    normalized = re.sub(
        r"(\d{2,4}[-./]\d{1,2}[-./]\d{1,2})(오전|오후)",
        r"\1 \2",
        normalized
    )

    for pattern in patterns:
        for match in re.finditer(pattern, normalized):
            year, month, day = match.groups()
            if _is_valid_date_parts(year, month, day):
                return f"{year}-{month.zfill(2)}-{day.zfill(2)}"

    return None


def extract_date(line_result):
    for line in line_result["line_result"]:
        text = line["joined_text"]

        # 전화번호 / 사업자번호 줄은 날짜 후보에서 제외
        if _looks_like_phone(text):
            continue
        if _looks_like_bizno(text):
            continue

        found = _find_valid_date(text, DATE_PATTERNS)
        if found:
            return found
    return None


# -------------------------------------합계 금액--------------------------------------

TOTAL_KEYWORDS = [
    r"합\s*계(?:\s*금액)?",
    r"총\s*계|총\s*액",
    r"(?:받(?:은|을)?|밖(?:은|을)?)\s*(?:금|큼)\s*액",
    r"청구\s*(?:금|큼)\s*액",
    r"결제\s*(?:금|큼)\s*액",
    r"판매\s*(?:금|큼)\s*액",
    r"승인\s*(?:금|큼)\s*액",
    r"카드\s*(?:금|큼)\s*액",
    r"총\s*결제\s*(?:금|큼)\s*액",
    r"총\s*구매\s*(?:금|큼)\s*액",
]


def extract_total_amount(line_result: Dict[str, Any]) -> Optional[int]:
    lines = line_result["line_result"]
    if not lines:
        return None

    max_y = max(line["y_center"] for line in lines)
    bottom_limit = max_y * 0.5

    candidates = []

    for line in lines:
        if line["y_center"] < bottom_limit:
            continue

        text = line["joined_text"]

        if any(re.search(pattern, text) for pattern in TOTAL_KEYWORDS):
            nums = re.findall(r"\d[\d,\.]*", text)
            if nums:
                raw = nums[-1].replace(",", "").replace(".", "")
                if raw.isdigit():
                    candidates.append((line["y_center"], int(raw), text))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


# ---------------------------------품목 별 정보-------------------------------------------------


def find_item_header_index(line_result: Dict[str, Any]) -> tuple[Optional[int], Optional[Dict[str, bool]]]:
    header_keywords = ["상품명", "상품", "품명", "메뉴", "메뉴명", "제품", "제품명", "PDS"]
    price_keywords = ["단가", "가격", "판매가"]
    qty_keywords = ["수량", "수", "개수", "수량(개)"]
    amount_keywords = ["금액", "합계", "판매금액"]

    best_idx = None
    best_score = 0
    best_header_info = None

    for i, line in enumerate(line_result["line_result"]):
        text = line["joined_text"].replace(" ", "")

        has_name = any(k in text for k in header_keywords)
        has_price = any(k in text for k in price_keywords)
        has_qty = any(k in text for k in qty_keywords)
        has_amount = any(k in text for k in amount_keywords)

        score = 0
        if has_name:
            score += 2
        if has_price:
            score += 1
        if has_qty:
            score += 1
        if has_amount:
            score += 1

        if score >= 3 and score > best_score:
            best_score = score
            best_idx = i
            best_header_info = {
                "has_name": has_name,
                "has_price": has_price,
                "has_qty": has_qty,
                "has_amount": has_amount,
            }

    return best_idx, best_header_info


def _clean_number_token(token: str) -> Optional[int]:
    cleaned = token.replace(",", "").replace(".", "").strip()
    if re.fullmatch(r"\d+", cleaned):
        return int(cleaned)
    return None


def parse_item_line(line: Dict[str, Any], header_info: Dict[str, bool]) -> Optional[Dict[str, Any]]:
    texts = line["texts"]

    numeric_tokens = []
    text_tokens = []

    for t in texts:
        value = _clean_number_token(t)
        if value is not None:
            numeric_tokens.append(value)
        else:
            text_tokens.append(t)

    if not text_tokens:
        return None

    item_name = " ".join(text_tokens).strip()
    nums = numeric_tokens

    unit_price = None
    quantity = None
    line_total = None

    has_price = header_info.get("has_price", False)
    has_qty = header_info.get("has_qty", False)
    has_amount = header_info.get("has_amount", False)

    if has_price and has_qty and has_amount:
        if len(nums) >= 3:
            unit_price, quantity, line_total = nums[0], nums[1], nums[2]
        else:
            return None

    elif (not has_price) and has_qty and has_amount:
        if len(nums) >= 2:
            quantity, line_total = nums[0], nums[1]
        else:
            return None

    elif has_price and (not has_qty) and has_amount:
        if len(nums) >= 2:
            unit_price, line_total = nums[0], nums[1]
        else:
            return None

    elif (not has_price) and (not has_qty) and has_amount:
        if len(nums) >= 1:
            line_total = nums[0]
        else:
            return None

    elif has_price and has_qty and (not has_amount):
        if len(nums) >= 2:
            unit_price, quantity = nums[0], nums[1]
        else:
            return None

    else:
        return None

    return {
        "name": item_name,
        "quantity": quantity,
        "unit_price": unit_price,
        "line_total": line_total,
        "raw_line": line["joined_text"]
    }


def extract_items(line_result: Dict[str, Any]) -> List[Dict[str, Any]]:
    lines = line_result["line_result"]
    header_idx, header_info = find_item_header_index(line_result)

    if header_idx is None or header_info is None:
        return []

    items = []

    for line in lines[header_idx + 1:]:
        text = line["joined_text"]

        if any(k in text for k in [
            "합계", "합계금액", "총액", "받을금액",
            "부가세", "신용카드", "카드", "승인", "결제"
        ]):
            break

        parsed = parse_item_line(line, header_info)
        if parsed:
            items.append(parsed)

    return items


# ---------------------------------상호명---------------------------------------------

STORE_LABEL_PATTERNS = [
    r"\[\s*(?:매\s*장\s*명|상\s*호\s*명|가\s*맹\s*점\s*명)\s*\]",
]

STORE_NAME_STRONG_PATTERNS = [
    r"\(\s*[^)]*점\s*\)",
    r"(?:본\s*점|지\s*점|직\s*영\s*점)$",
    r".*점$",
]

ADDRESS_HINT_PATTERNS = [
    r"(?:서울|경기|인천|부산|대구|광주|대전|울산|세종|강원|충북|충남|전북|전남|경북|경남|제주)",
    r"(?:시|군|구|동|읍|면|리|로|길)\b",
]

STORE_BAD_HINTS = [
    "대표자", "대 표 자",
    "사업자", "사 업 자",
    "사업자번호", "사 업 자 번 호",
    "전화", "전 화", "tel",
    "주소", "주 소",
    "고객용", "고 객 용",
    "카드", "카 드",
    "승인", "승 인",
    "승인번호", "승 인 번 호",
    "매출", "매 출",
    "부가세", "부 가 세",
    "합계", "합 계",
    "공급가액", "공 급 가 액",
    "원산지", "원 산 지",
    "주문번호", "주 문 번 호",
    "주문내역", "주 문 내 역",
    "테이블", "테 이 블",
    "좌석", "좌 석",
    "포장", "포 장",
    "배달", "배 달",
    "결제", "결 제",
    "청구", "청 구",
    "할부", "할 부",
    "일시불", "일 시 불",
    "영수증", "영 수 증",
    "재발행", "재 발 행",
]

STORE_ONLY_BAD_PATTERNS = [
    r"^\s*\[?\s*영\s*수\s*증\s*\]?\s*$",
]

STORE_CLEAN_LABEL_PATTERN = r"^\s*\[\s*(?:매\s*장\s*명|상\s*호\s*명|가\s*맹\s*점\s*명)\s*\]\s*"


def _calc_hangul_ratio(text: str) -> float:
    chars = re.findall(r"[가-힣A-Za-z0-9]", text)
    if not chars:
        return 0.0
    hangul_alpha = re.findall(r"[가-힣A-Za-z]", text)
    return len(hangul_alpha) / len(chars)


def _looks_like_address(text: str) -> bool:
    return any(re.search(p, text) for p in ADDRESS_HINT_PATTERNS)


def _normalize_store_text(text: str) -> str:
    text = re.sub(STORE_CLEAN_LABEL_PATTERN, "", text).strip()
    text = re.sub(r"^\s*(?:상호|매장명|가맹점명)\s*[:：]?\s*", "", text).strip()
    return text


def _is_store_only_bad_text(text: str) -> bool:
    return any(re.search(p, text.strip()) for p in STORE_ONLY_BAD_PATTERNS)


def _line_used_for_date(line: Dict[str, Any]) -> bool:
    text = line["joined_text"]
    if _looks_like_phone(text) or _looks_like_bizno(text):
        return False
    return _find_valid_date(text, DATE_PATTERNS) is not None


def _line_used_for_total(line: Dict[str, Any]) -> bool:
    text = line["joined_text"]
    return any(re.search(pattern, text) for pattern in TOTAL_KEYWORDS)


def _build_item_line_nos(line_result: Dict[str, Any]) -> set:
    lines = line_result["line_result"]
    header_idx, header_info = find_item_header_index(line_result)

    if header_idx is None or header_info is None:
        return set()

    used = {header_idx}

    for i in range(header_idx + 1, len(lines)):
        text = lines[i]["joined_text"]

        if any(k in text for k in [
            "합계", "합계금액", "총액", "받을금액",
            "부가세", "신용카드", "카드", "승인", "결제"
        ]):
            break

        parsed = parse_item_line(lines[i], header_info)
        if parsed:
            used.add(i)

    return used


def _score_store_part(part: str) -> int:
    score = 0
    normalized = _normalize_store_text(part)

    if not normalized:
        return -999

    if _is_store_only_bad_text(normalized):
        score -= 200

    if any(re.search(p, normalized) for p in STORE_LABEL_PATTERNS):
        score += 60

    if any(re.search(p, normalized) for p in STORE_NAME_STRONG_PATTERNS):
        score += 80

    if _looks_like_phone(normalized):
        score -= 80
    if _looks_like_bizno(normalized):
        score -= 80
    if _find_valid_date(normalized, DATE_PATTERNS):
        score -= 60
    if _looks_like_address(normalized):
        score -= 40

    lower_text = normalized.lower()
    for bad in STORE_BAD_HINTS:
        if bad.lower() in lower_text:
            score -= 25

    digit_count = len(re.findall(r"\d", normalized))
    alpha_count = len(re.findall(r"[가-힣A-Za-z]", normalized))
    hangul_ratio = _calc_hangul_ratio(normalized)

    if alpha_count > 0:
        score += 10
    if hangul_ratio >= 0.7:
        score += 10
    elif hangul_ratio >= 0.5:
        score += 5

    if digit_count >= 7:
        score -= 25
    elif digit_count >= 5:
        score -= 15
    elif digit_count >= 3:
        score -= 8

    if re.fullmatch(r"[^\w가-힣A-Za-z]+", normalized):
        score -= 30

    return score


def _find_special_store_part(text: str) -> Optional[str]:
    """
    특이 케이스:
    한글문자열 / 사업자번호 / 기타...
    구조면 첫 번째 한글문자열을 상호명으로 간주한다.
    """
    if "/" not in text:
        return None

    parts = [p.strip() for p in text.split("/") if p.strip()]
    if len(parts) < 2:
        return None

    # 첫 part는 한글 위주의 이름이어야 함
    first = _normalize_store_text(parts[0])
    if not first:
        return None

    first_has_hangul = re.search(r"[가-힣A-Za-z]", first) is not None
    first_digit_count = len(re.findall(r"\d", first))

    if not first_has_hangul:
        return None
    if first_digit_count >= 3:
        return None
    if _looks_like_phone(first) or _looks_like_bizno(first) or _looks_like_address(first):
        return None

    # 뒤 part들 중 하나라도 사업자번호면 특이 케이스 인정
    has_bizno_after = any(_looks_like_bizno(p) for p in parts[1:])
    if not has_bizno_after:
        return None

    return first


def _score_store_line(
    line: Dict[str, Any],
    line_idx: int,
    item_line_nos: set,
) -> int:
    text = line["joined_text"].strip()
    if not text:
        return -999

    score = 0

    if _line_used_for_date(line):
        score -= 50
    if line_idx in item_line_nos:
        score -= 50
    if _line_used_for_total(line):
        score -= 50

    if _is_store_only_bad_text(text):
        score -= 80

    if any(re.search(p, text) for p in STORE_LABEL_PATTERNS):
        score += 60

    if any(re.search(p, text) for p in STORE_NAME_STRONG_PATTERNS):
        score += 80

    # 특이 케이스: 상호명/사업자번호/기타...
    special_store = _find_special_store_part(text)
    if special_store is not None:
        score += 100

    if _looks_like_phone(text):
        score -= 25
    if _looks_like_bizno(text):
        score -= 25
    if _looks_like_address(text):
        score -= 20

    lower_text = text.lower()
    for bad in STORE_BAD_HINTS:
        if bad.lower() in lower_text:
            score -= 18

    return score


def _score_store_box(text: str) -> int:
    text = text.strip()
    if not text:
        return -999

    score = 0

    if _is_store_only_bad_text(text):
        score -= 200

    if any(re.search(p, text) for p in STORE_LABEL_PATTERNS):
        score += 100

    normalized = _normalize_store_text(text)

    if any(re.search(p, normalized) for p in STORE_NAME_STRONG_PATTERNS):
        score += 100

    if _looks_like_phone(normalized):
        score -= 30
    if _looks_like_bizno(normalized):
        score -= 30
    if _find_valid_date(normalized, DATE_PATTERNS):
        score -= 30
    if _looks_like_address(normalized):
        score -= 40

    lower_text = normalized.lower()
    for bad in STORE_BAD_HINTS:
        if bad.lower() in lower_text:
            score -= 20

    digit_count = len(re.findall(r"\d", normalized))
    alpha_count = len(re.findall(r"[가-힣A-Za-z]", normalized))
    hangul_ratio = _calc_hangul_ratio(normalized)

    if alpha_count > 0:
        score += 10
    if hangul_ratio >= 0.7:
        score += 10
    elif hangul_ratio >= 0.5:
        score += 5

    if digit_count >= 7:
        score -= 25
    elif digit_count >= 5:
        score -= 15
    elif digit_count >= 3:
        score -= 8

    if re.fullmatch(r"[^\w가-힣A-Za-z]+", normalized):
        score -= 30

    return score


def extract_store_name(line_result: Dict[str, Any]) -> Optional[str]:
    lines = line_result["line_result"]
    if not lines:
        return None

    item_line_nos = _build_item_line_nos(line_result)

    scored_lines = []
    for idx, line in enumerate(lines):
        score = _score_store_line(line, idx, item_line_nos)
        scored_lines.append((score, idx, line))

    scored_lines.sort(key=lambda x: x[0], reverse=True)
    top3 = scored_lines[:3]

    print("\n===== 상호명 Top3 line 후보 =====")
    for rank, (score, idx, line) in enumerate(top3, start=1):
        print(f"{rank}. line_no={line['line_no']} / score={score} / text={line['joined_text']}")
    print("=" * 30)

    if not top3:
        return None

    best_final = None
    best_final_score = -10**9

    for line_score, line_idx, line in top3:
        # 특이 케이스면 line 자체에서 바로 상호명 후보 추출
        special_store = _find_special_store_part(line["joined_text"])
        if special_store is not None:
            final_score = line_score + 100
            if final_score > best_final_score:
                best_final_score = final_score
                best_final = special_store

        # 일반 box 평가
        for item in line["items"]:
            box_text = str(item["text"]).strip()
            box_score = _score_store_box(box_text)
            final_score = int(line_score * 0.35 + box_score * 0.65)

            if final_score > best_final_score:
                best_final_score = final_score
                best_final = box_text

    if not best_final:
        best_final = top3[0][2]["joined_text"]

    best_final = _normalize_store_text(best_final)
    return best_final if best_final else None


# --------------------------------------------최종 실행 파트--------------------------------------------------

def parse_receipt(raw_result: Dict[str, Any]) -> Dict[str, Any]:
    line_result = build_line_result(raw_result)

    parsed = {
        "image_path": raw_result.get("image_path"),
        "store_name": extract_store_name(line_result),
        "purchase_date": extract_date(line_result),
        "items": extract_items(line_result),
        "total_amount": extract_total_amount(line_result),
        "line_result": line_result["line_result"],
    }

    print("\n===== 파싱 결과 미리보기 =====")
    print(f"상호명: {parsed['store_name']}")
    print(f"날짜: {parsed['purchase_date']}")
    print(f"합계금액: {parsed['total_amount']}")
    print("품목들:")
    for item in parsed["items"]:
        print(f"  - {item['name']} / 수량: {item['quantity']} / 단가: {item['unit_price']} / 금액: {item['line_total']}")
    print("=" * 30)

    return parsed


def load_raw_result(json_path: str) -> Dict[str, Any]:
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_parsed_result(parsed_result: Dict[str, Any], output_path: str) -> None:
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(parsed_result, f, ensure_ascii=False, indent=2)


def run_receipt_parser(
    raw_json_path: str = "receipt_ocr_raw.json",
    output_path: str = "receipt_ocr_parsed.json",
) -> Dict[str, Any]:
    raw_result = load_raw_result(raw_json_path)
    parsed_result = parse_receipt(raw_result)
    save_parsed_result(parsed_result, output_path)
    print(f"파싱 결과 저장 완료: {output_path}")
    return parsed_result


if __name__ == "__main__":
    run_receipt_parser()