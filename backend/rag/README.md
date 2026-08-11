# Livestock RAG System

축산 방역·법령·지원사업 문서를 기반으로 구축한 RAG(Retrieval-Augmented Generation) 시스템입니다.

이 모듈은 사용자 질문을 분석해 적절한 질의 유형으로 라우팅하고, Azure AI Search에서 관련 문서를 검색한 뒤 LLM이 근거 기반 답변을 생성하도록 구성되어 있습니다.

## 1. 주요 기능

- 구제역 질병 정보 질의응답
- 구제역 의심축 발견 후 현장 대응 안내
- 가축전염병 관련 법령 질의
- 축사시설현대화 지원사업 질의
- 구제역 발생 및 역학조사 분석
- 복합 질의 라우팅
- 후속 대화 문맥 처리
- 문서 근거 citation 표시
- 문서 범위 밖 질문 거절
- short / normal / detailed 답변 모드
- 생성 답변 후처리 및 텍스트 정리

## 2. RAG 처리 흐름

사용자 질문
→ Query Router
→ 질의 유형 결정
→ Embedding 생성
→ Azure AI Search
→ Hybrid + Semantic Search
→ 관련 Context 선정
→ LLM 답변 생성
→ Citation Resolution
→ Text Cleanup
→ FastAPI Response

