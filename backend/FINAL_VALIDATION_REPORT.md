# RAG 최종 검증 보고서

## 1. 최종 검증 요약

- Pytest: 37 / 37 PASS
- User QA: 30 / 30 PASS
- Follow-up QA: 6 / 6 PASS
- Router: 60 / 60 PASS
- Negative Router: 20 / 20 PASS
- Router Total: 80 / 80
- Search Top-1: 81.67%
- Search Top-3: 100%
- Search Top-5: 100%
- Search Miss: 0
- OOD 거절: 정상
- Citation: 정상
- Legal stability: 정상
- HTTP error: 0

## 2. 검색 성능

총 60개 검색 평가 결과:

- Top-1: 49 / 60 (81.67%)
- Top-3: 60 / 60 (100.00%)
- Top-5: 60 / 60 (100.00%)
- Miss: 0

모든 평가 질문에서 정답 근거가 Top-3 안에 포함되었다.

## 3. 사용자 QA 평가

총 30개 사용자형 질문 평가 결과:

- HTTP 정상: 30 / 30
- Cleanup 정상: 30 / 30
- 문서 범위 밖 질문 거절: 2 / 2
- HTTP 오류: 0

평가 범위에는 구제역 신고, 현장 대응, 법령, 지원사업, 역학조사, 문서 범위 밖 질문이 포함되었다.

## 4. 후속 대화 평가

총 6개 후속 질문 평가 결과:

- HTTP 정상: 6 / 6
- Cleanup 정상: 6 / 6
- HTTP 오류: 0

이전 대화 문맥을 유지한 축약형 후속 질문 처리도 정상 동작하였다.

## 5. 라우터 평가

기본 라우터:

- 60 / 60
- 정확도 100%

Negative / Overrouting 평가:

- 20 / 20
- 정확도 100%

총 라우터 평가:

- 80 / 80
- 정확도 100%

## 6. 법령 안정성

가축전염병 예방법 제11조 신고 의무자 질문에 대해 반복 테스트를 수행하였다.

주요 신고 주체:

- 소유자 또는 관리자
- 축산계열화사업자
- 수의사
- 연구책임자
- 동물약품 또는 사료 판매자
- 가축운송업자

안정성 테스트 결과: PASS

## 7. 문서 범위 밖 질문

다음과 같은 문서 범위 밖 질문은 일반지식으로 임의 답변하지 않는다.

- 파이썬 리스트 정렬 방법
- 오늘 서울 날씨

응답:

제공된 문서에서는 해당 내용을 확인할 수 없습니다.

sources는 빈 배열로 반환된다.

## 8. 답변 모드

지원 모드:

- short
- normal
- detailed

세 모드 모두 테스트 통과하였다.

## 9. Cleanup

최종 cleanup 단위 테스트:

- 12 / 12 PASS

주요 처리:

- 불필요한 메타 제목 제거
- 근거/출처 메타 문구 제거
- 후속 제안 제거
- citation 정리
- 중복 citation 제거
- 날짜 줄바꿈 복구
- 빈 목록 기호 제거
- escape 문자 정리

## 10. Semantic Ranker

현재 검색은 Azure AI Search Semantic Ranker 활성화 상태를 기준으로 검증하였다.

Free Semantic Query 월 한도 초과 후 Standard 플랜으로 변경하여 정상 복구하였다.

Semantic Ranker를 비활성화하면 검색 순위와 reranker score 기반 로직이 달라질 수 있으므로, 본 검증 결과는 Semantic Ranker 활성화 상태를 기준으로 한다.

## 11. 최종 판단

현재 RAG 시스템은 다음 파이프라인에서 정상 동작이 확인되었다.

사용자 질문
→ Query Router
→ Hybrid + Semantic Search
→ Context 구성
→ LLM 답변 생성
→ Citation Resolution
→ Text Cleanup
→ FastAPI 응답

현재 버전은 기능 검증 단계 완료 상태로 판단한다.

단, 실제 운영에서는 사용자 표현 다양성, 오타, 장문 복합질문, 문서 추가·변경에 대한 지속적인 평가가 필요하다.
