# 외부 라이브러리와 참고 자료

## Three.js / OrbitControls

- 버전: **0.170.0 (r170)**
- 배포 원본: npm 공식 `three@0.170.0` 패키지
- 소스: <https://github.com/mrdoob/three.js/tree/r170>
- 라이선스: **MIT**
- 라이선스 원문: [`simulator/static/vendor/LICENSE`](simulator/static/vendor/LICENSE)
- 포함 파일: `three.module.min.js`, `OrbitControls.js`

두 파일은 인터넷 연결 없이 브라우저에서 불러오도록 저장소에 포함했습니다. 배포할 때 라이선스 원문을 함께 유지해야 합니다.

## 모델과 외형

로봇·가상 인물·실내 장면은 `simulator/static/app.js`에서 기본 도형으로 구성합니다. 별도의 외부 3D 모델 파일은 사용하지 않습니다. 로봇의 구조는 [한백전자 SerBot AGV 제품 정보](https://hanback.com/ko/archives/11695)를 참고한 간략 표현입니다. 제조사 CAD나 공식 모델을 배포하는 것은 아닙니다.

원래 로봇 제어 프로젝트: <https://github.com/tlstngud/tteooreum-robot>. 이 저장소는 개발한 시뮬레이터 코드만 분리했으며, 해당 저장소의 하드웨어 제어 코드나 Git 이력을 포함하지 않습니다.

프로젝트 자체의 소스 라이선스는 별도로 지정하지 않았습니다. 위 MIT 라이선스는 명시된 외부 라이브러리에 적용됩니다.
