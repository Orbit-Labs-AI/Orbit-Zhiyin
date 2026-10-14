# Orbit 0.0.4 第三方许可说明

本次原样迁移既有安装包，保留其内含许可文件。第三方组件仍按各自许可证授权，Orbit 发布仓库的专有许可不覆盖这些组件。

[BUNDLED-LICENSES.zip](BUNDLED-LICENSES.zip) 是从原 ZIP 安装包逐字节提取的许可文件副本，保留包内路径，方便在不运行 App 的情况下查阅；安装包未被修改。

## 安装包元数据中列出的第三方组件

下表依据安装包内的 `.dist-info/METADATA`，仅列出有相应元数据的组件，不表示所有打包依赖的完整清单。包含的运行时、间接依赖及库内嵌代码仍适用各自许可。

| 组件 | 版本 | 元数据中的许可标识或说明 |
| --- | --- | --- |
| attrs | 26.1.0 | MIT |
| click | 8.5.0 | BSD-3-Clause |
| fastapi | 0.115.12 | OSI Approved :: MIT License |
| jieba | 0.42.1 | MIT |
| jsonschema | 4.26.0 | MIT |
| numpy | 2.5.3 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| pydantic | 2.11.7 | MIT |
| scikit-learn | 1.7.2 | BSD-3-Clause |
| scipy | 1.18.1 | 随组件完整许可文件 |
| uvicorn | 0.34.3 | BSD-3-Clause |

## 保留的许可文件

本附件包含 30 个安装包原有许可文件，具体路径如下。提取这些文件不代表完成了独立、穷尽的第三方合规审计，也没有为本次迁移声明新的再许可权。

- `Orbit.app/Contents/Resources/backend/_internal/numpy-2.5.3.dist-info/licenses/numpy/linalg/lapack_lite/LICENSE.txt`
- `Orbit.app/Contents/Resources/backend/_internal/numpy-2.5.3.dist-info/licenses/numpy/ma/LICENSE`
- `Orbit.app/Contents/Resources/backend/_internal/numpy-2.5.3.dist-info/licenses/numpy/_core/include/numpy/libdivide/LICENSE.txt`
- `Orbit.app/Contents/Resources/backend/_internal/numpy-2.5.3.dist-info/licenses/numpy/_core/src/npysort/x86-simd-sort/LICENSE.md`
- `Orbit.app/Contents/Resources/backend/_internal/numpy-2.5.3.dist-info/licenses/numpy/_core/src/highway/LICENSE`
- `Orbit.app/Contents/Resources/backend/_internal/numpy-2.5.3.dist-info/licenses/numpy/_core/src/multiarray/dragon4_LICENSE.txt`
- `Orbit.app/Contents/Resources/backend/_internal/numpy-2.5.3.dist-info/licenses/numpy/_core/src/common/pythoncapi-compat/COPYING`
- `Orbit.app/Contents/Resources/backend/_internal/numpy-2.5.3.dist-info/licenses/numpy/_core/src/umath/svml/LICENSE`
- `Orbit.app/Contents/Resources/backend/_internal/numpy-2.5.3.dist-info/licenses/numpy/fft/pocketfft/LICENSE.md`
- `Orbit.app/Contents/Resources/backend/_internal/numpy-2.5.3.dist-info/licenses/numpy/random/LICENSE.md`
- `Orbit.app/Contents/Resources/backend/_internal/numpy-2.5.3.dist-info/licenses/numpy/random/src/mt19937/LICENSE.md`
- `Orbit.app/Contents/Resources/backend/_internal/numpy-2.5.3.dist-info/licenses/numpy/random/src/sfc64/LICENSE.md`
- `Orbit.app/Contents/Resources/backend/_internal/numpy-2.5.3.dist-info/licenses/numpy/random/src/pcg64/LICENSE.md`
- `Orbit.app/Contents/Resources/backend/_internal/numpy-2.5.3.dist-info/licenses/numpy/random/src/philox/LICENSE.md`
- `Orbit.app/Contents/Resources/backend/_internal/numpy-2.5.3.dist-info/licenses/numpy/random/src/splitmix64/LICENSE.md`
- `Orbit.app/Contents/Resources/backend/_internal/numpy-2.5.3.dist-info/licenses/numpy/random/src/distributions/LICENSE.md`
- `Orbit.app/Contents/Resources/backend/_internal/numpy-2.5.3.dist-info/licenses/LICENSE.txt`
- `Orbit.app/Contents/Resources/backend/_internal/click-8.5.0.dist-info/licenses/LICENSE.txt`
- `Orbit.app/Contents/Resources/backend/_internal/scikit_learn-1.7.2.dist-info/licenses/COPYING`
- `Orbit.app/Contents/Resources/backend/_internal/orbit_catalog-0.1.0.dist-info/licenses/LICENSE`
- `Orbit.app/Contents/Resources/backend/_internal/jsonschema-4.26.0.dist-info/licenses/COPYING`
- `Orbit.app/Contents/Resources/backend/_internal/orbit_data-0.2.0.dist-info/licenses/LICENSE`
- `Orbit.app/Contents/Resources/backend/_internal/sklearn/externals/array_api_compat/LICENSE`
- `Orbit.app/Contents/Resources/backend/_internal/sklearn/externals/array_api_extra/LICENSE`
- `Orbit.app/Contents/Resources/backend/_internal/fastapi-0.115.12.dist-info/licenses/LICENSE`
- `Orbit.app/Contents/Resources/backend/_internal/pydantic-2.11.7.dist-info/licenses/LICENSE`
- `Orbit.app/Contents/Resources/backend/_internal/attrs-26.1.0.dist-info/licenses/LICENSE`
- `Orbit.app/Contents/Resources/backend/_internal/orbit_backend-0.13.6.dist-info/licenses/LICENSE`
- `Orbit.app/Contents/Resources/backend/_internal/uvicorn-0.34.3.dist-info/licenses/LICENSE.md`
- `Orbit.app/Contents/Resources/backend/_internal/scipy-1.18.1.dist-info/LICENSE.txt`
