from supabase import create_client

class SupabaseManager:
    def __init__(self):
        # 1. Supabase 연동 정보
        self.url = "https://djjkvygcgcmmaowbnxjq.supabase.co"
        self.key = "sb_publishable_ZX9Jjwq6LNFYMAlfu5ZGSg_cqtMwPVy"
        self.supabase = create_client(self.url, self.key)

    def get_image_list(self, bucket_name="image"):
        """Storage 버킷에 있는 파일 목록을 가져옵니다."""
        return self.supabase.storage.from_(bucket_name).list()

    def get_image_url(self, file_name, bucket_name="image"):
        """특정 이미지의 Public URL을 가져옵니다."""
        return self.supabase.storage.from_(bucket_name).get_public_url(file_name)

    def insert_ocr_result(self, image_name, all_text, confidence, ocr_items):
        # 1. ocr_raw 테이블에 영수증 저장
        raw_data = {
            "image_name": image_name,
            "all_text": all_text,
            "confidence": confidence
        }
        raw_result = self.supabase.table("ocr_raw").insert(raw_data).execute()
    
        # 2. 저장된 행의 id 가져오기
        ocr_raw_id = raw_result.data[0]["id"]
    
        # 3. ocr_raw_items에 텍스트 조각 38개 저장
        items_data = [
            {
                "ocr_raw_id": ocr_raw_id,
                "text": item["text"],
                "score": item["score"],
                "box": item["box"]
            }
            for item in ocr_items
        ]
        return self.supabase.table("ocr_raw_items").insert(items_data).execute()