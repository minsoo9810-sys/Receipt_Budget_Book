# item_y.py

import json
import re

# =================================================================
# 1. $y$ 좌표 기반 격자 파싱 알고리즘 (질문자님이 올린 JSON 저격 커스텀)
# =================================================================
def parse_items_by_y_coordinate(raw_json_path="receipt_ocr_raw.json", y_threshold=30):
    with open(raw_json_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    items = raw_data.get("ocr_result", [])
    if not items:
        return []

    # [1단계] 모든 텍스트 조각을 세로 Y좌표(y1) 기준으로 정렬
    items_sorted_by_y = sorted(items, key=lambda x: x["box"][0][1])
    
    lines = []
    current_line = []
    current_y = -1
    
    # [2단계] Y좌표 차이가 오차범위(30px) 이내인 글자들을 하나의 줄로 묶기
    for item in items_sorted_by_y:
        box = item["box"]
        y1 = box[0][1] # 좌측 상단 y
        x1 = box[0][0] # 좌측 상단 x
        text = item["text"]
        
        if current_y == -1 or abs(y1 - current_y) <= y_threshold:
            current_line.append({"text": text, "x": x1, "y": y1})
            current_y = y1 if current_y == -1 else (current_y + y1) / 2
        else:
            lines.append(sorted(current_line, key=lambda k: k["x"]))
            current_line = [{"text": text, "x": x1, "y": y1}]
            current_y = y1
            
    if current_line:
        lines.append(sorted(current_line, key=lambda k: k["x"]))

    # [3단계] 품목 구역 탐색 및 X좌표 기반 알맹이 쪼개기
    parsed_items = []
    is_item_section = False
    
    for line in lines:
        line_text_collapsed = "".join([item["text"] for item in line]).replace(" ", "")
        
        # 깃발 켜기 (올려주신 데이터에 '메뉴'가 포함되어 있음)
        if any(k in line_text_collapsed for k in ["메뉴", "상품명", "품목", "단가"]):
            is_item_section = True
            continue
        # 깃발 끄기
        if any(k in line_text_collapsed for k in ["부가세", "합계", "결제수단"]):
            is_item_section = False
            
        if is_item_section:
            item_name = ""
            quantity = 1
            price = 0
            
            for part in line:
                val = part["text"].strip()
                x_coord = part["x"]
                clean_num = "".join(filter(str.isdigit, val))
                
                # 가로 X좌표 위치 대조
                # 초코 크로아상의 x좌표가 대략 598 부근이므로 x < 1000 조건 부여
                if x_coord < 1000 and not clean_num:
                    item_name += " " + val
                elif clean_num:
                    num = int(clean_num)
                    if num < 50 and quantity == 1:  # 숫자가 작으면 수량
                        quantity = num
                    else:  # 숫자가 크면 가격
                        price = num
                        
            if item_name.strip() and price > 0:
                parsed_items.append({
                    "item_name": item_name.strip(),
                    "quantity": quantity,
                    "price": price
                })
                
    return parsed_items

# =================================================================
# 2. 실행 제어부
# =================================================================
def main():
    print("⚙️ 1. 제공된 receipt_ocr_raw.json (초코 크로아상 영수증 데이터) 파싱 시작...")
    extracted_items = parse_items_by_y_coordinate()
    
    print("\n==========================================")
    print("🎯 [Y열 좌표 분석 알고리즘 결과]")
    print("==========================================")
    if extracted_items:
        for idx, item in enumerate(extracted_items, start=1):
            print(f"   [{idx}] 품목명: {item['item_name']}")
            print(f"       ➔ 수량: {item['quantity']}개")
            print(f"       ➔ 가격: {item['price']:,}원")
            print("------------------------------------------")
        print("\n🎉 알고리즘이 정상 작동합니다! 이제 이 데이터를 DB에 쏘면 됩니다.")
    else:
        print("⚠️ 품목을 추출하지 못했습니다. 허용 오차(y_threshold)나 경계면을 조절해 주세요.")

if __name__ == "__main__":
    main()