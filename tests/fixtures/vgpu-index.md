Title: NVIDIA Virtual GPU (vGPU) Software - NVIDIA Docs

URL Source: https://docs.nvidia.com/vgpu/index.html

Markdown Content:
#### Active vGPU Software Releases

| vGPU Software Release | Driver Branch | [vGPU Branch Type](https://docs.nvidia.com/grid/news/vgpu-software-lifecycle-policy/) | Latest Release in Branch | Release Date | EOL Date |
| --- | --- | --- | --- | --- | --- |
| [NVIDIA vGPU 19](https://docs.nvidia.com/vgpu/19.0/index.html) | R580 | [Long-Term Support](https://docs.nvidia.com/vgpu/news/vgpu-software-lifecycle-policy/#ltsb-releases) | 19.1 | September 2025 | July 2028 |
| [NVIDIA vGPU 18](https://docs.nvidia.com/vgpu/18.0/index.html.md) | R570 | [Production](https://nam11.safelinks.protection.outlook.com/?url=https%3A%2F%2Fdocs.nvidia.com%2Fvgpu%2Fnews%2Fvgpu-software-lifecycle-policy%2F%23nfb-releases&data=05%7C02%7Crkashireddy%40nvidia.com%7C0bdf3c8848104340ea2b08dd5b2f3613%7C43083d15727340c1b7db39efd9ccc17a%7C0%7C0%7C638766980564840794%7CUnknown%7CTWFpbGZsb3d8eyJFbXB0eU1hcGkiOnRydWUsIlYiOiIwLjAuMDAwMCIsIlAiOiJXaW4zMiIsIkFOIjoiTWFpbCIsIldUIjoyfQ%3D%3D%7C0%7C%7C%7C&sdata=7NXdCSOkkNVIhSujWrhPHW2Lv5vO9xbCKEhNyFQU2OI%3D&reserved=0) | 18.4 | July 2025 | March 2026 |
| [NVIDIA vGPU 16](https://docs.nvidia.com/vgpu/16.0/index.html) | R535 | [Long-Term Support](https://docs.nvidia.com/vgpu/news/vgpu-software-lifecycle-policy/#ltsb-releases) | 16.11 | July 2025 | July 2026 |

#### Older vGPU Software Releases

| vGPU Software Release | Driver Branch | [vGPU Branch Type](https://docs.nvidia.com/grid/news/vgpu-software-lifecycle-policy/) | Latest Release in Branch | Release Date | EOL Date |
| --- | --- | --- | --- | --- | --- |
| [NVIDIA vGPU 17](https://docs.nvidia.com/grid/17.0/index.html) | R550 | EOL Production | 17.6 | April 2025 | June 2025 |
| [NVIDIA vGPU 15](https://docs.nvidia.com/grid/15.0/index.html) | R525 | EOL Production | 15.4 | October 2023 | December 2023 |
| [NVIDIA vGPU 14](https://docs.nvidia.com/grid/14.0/index.html) | R510 | EOL Production | 14.4 | December 2022 | February 2023 |
| [NVIDIA vGPU 13](https://docs.nvidia.com/grid/13.0/index.html) | R470 | EOL Long-Term Support | 13.12 | July 2024 | August 2024 |
| [NVIDIA vGPU 12](https://docs.nvidia.com/grid/12.0/index.html) | R460 | EOL Production | 12.4 | October 2021 | January 2022 |
| [NVIDIA vGPU 11](https://docs.nvidia.com/grid/11.0/index.html) | R450 | EOL Long-Term Support | 11.13 | June 2023 | July 2023 |
| [NVIDIA vGPU 10](https://docs.nvidia.com/grid/10.0/index.html) | R440 | EOL Production | 10.4 | September 2020 | December 2020 |
| [NVIDIA vGPU 9](https://docs.nvidia.com/grid/9.0/index.html) | R430 | EOL Production | 9.4 | June 2020 | June 2020 |
| [NVIDIA vGPU 8](https://docs.nvidia.com/grid/8.0/index.html) | R418 | EOL Long-Term Support | 8.10 | January 2022 | April 2022 |
| [NVIDIA vGPU 7](https://docs.nvidia.com/grid/7.0/index.html) | R410 | EOL Production | 7.5 | October 2019 | October 2019 |
| [NVIDIA vGPU 6](https://docs.nvidia.com/grid/6.0/index.html) | R390 | EOL[1](https://docs.nvidia.com/grid/index.html.md#release-branches-2-6-support-policy-note) | 6.4 | February 2019 | March 2019 |
| [NVIDIA vGPU 5](https://docs.nvidia.com/grid/5.0/index.html) | R384 | EOL | 5.4 | August 2018 | August 2018 |
| [NVIDIA GRID 4](https://docs.nvidia.com/grid/4.10/index.html) | R367 | EOL | 4.10 | January 2020 | January 2020 |
| [NVIDIA GRID 3](https://docs.nvidia.com/grid/3.4/index.html) | R361 | EOL | 3.4 | March 2017 | April 2019 |
| [NVIDIA GRID 2](https://docs.nvidia.com/grid/2.5/index.html) | R352 | EOL | 2.5 | March 2017 | August 2018 |

1.   Release branches 2-6 predate the current support policy, which was introduced in vGPU software 7.0.

### Branch Types

What Release of vGPU Software Should I Be Using?

[NVIDIA Virtual GPU Software Lifecycle Policy](https://docs.nvidia.com/grid/news/vgpu-software-lifecycle-policy/#abstract) defines the following branch statuses for NVIDIA vGPU software releases:

*   **Production Branch releases**, which are supported for 1 year
*   **Long Term Support Branch releases**, which are supported for 3 years

The release of vGPU software that you should use depends on whether you require a longer cycle of support or you want access to new features as they become available:

*   If you require a longer cycle of support from your deployed branch, for example, in production environments, use the latest release in a**Long Term Support Branch**. If all the features that you require are available in your currently deployed branch, you don't need to upgrade to a later Long Term Support Branch until your currently deployed branch reaches EOL.
*   If you want access to new features as they become available, for example, in test environments, use the latest**Production Branch**release.

Driver Versions
---------------

**Note:**The Linux vGPU Manager is for Linux-style hypervisors, namely: Citrix Hypervisor, Linux with KVM, Red Hat Enterprise Linux with KVM, Ubuntu, and VMware vSphere.

[Branch status](https://docs.nvidia.com/vgpu/news/vgpu-software-lifecycle-policy/): Long-Term Support Branch supported until July 2028

| vGPU Software | Linux vGPU Manager | Windows vGPU Manager | Linux Driver | Windows Driver | Release Date |
| --- | --- | --- | --- | --- | --- |
| [19.1](https://docs.nvidia.com/vgpu/19.0/index.html) | 580.82.02 | 581.15 | 580.82.07 | 581.15 | September 2025 |
| [19.0](https://docs.nvidia.com/vgpu/19.0/index.html) | 580.65.05 | 580.86 | 580.65.06 | 580.88 | August 2025 |

[Branch status](https://docs.nvidia.com/vgpu/news/vgpu-software-lifecycle-policy/): Production Branch supported until March 2026

| vGPU Software | Linux vGPU Manager | Windows vGPU Manager | Linux Driver | Windows Driver | Release Date |
| --- | --- | --- | --- | --- | --- |
| [18.4](https://docs.nvidia.com/vgpu/18.0/index.html.md) | 570.172.07 | 573.55 | 570.172.08 | 573.48 | July 2025 |
| [18.3](https://docs.nvidia.com/vgpu/18.0/index.html.md) | 570.158.02 | 573.36 | 570.158.01 | 573.39 | June 2025 |
| [18.2](https://docs.nvidia.com/vgpu/18.0/index.html.md) | 570.148.06 | 573.07 | 570.148.08 | 573.07 | May 2025 |
| [18.1](https://docs.nvidia.com/vgpu/18.0/index.html.md) | 570.133.10 | 572.83 | 570.133.20 | 572.83 | March 2025 |
| [18.0](https://docs.nvidia.com/vgpu/18.0/index.html.md) | 570.124.03 | 572.60 | 570.124.06 | 572.60 | March 2025 |

[Branch status](https://docs.nvidia.com/vgpu/news/vgpu-software-lifecycle-policy/): Production Branch supported until June 2025

| vGPU Software | Linux vGPU Manager | Windows vGPU Manager | Linux Driver | Windows Driver | Release Date |
| --- | --- | --- | --- | --- | --- |
| [17.6](https://docs.nvidia.com/vgpu/17.0/index.html) | 550.163.02 | 553.74 | 550.163.01 | 553.74 | April 2025 |
| [17.5](https://docs.nvidia.com/vgpu/17.0/index.html) | 550.144.02 | 553.56 | 550.144.03 | 553.62 | January 2025 |
| [17.4](https://docs.nvidia.com/vgpu/17.0/index.html) | 550.127.06 | 553.20 | 550.127.05 | 553.24 | October 2024 |
| [17.3](https://docs.nvidia.com/vgpu/17.0/index.html) | 550.90.05 | 552.55 | 550.90.07 | 552.74 | July 2024 |
| 17.2 | 550.90.05 | 552.55 | 550.90.07 | 552.55 | June 2024 |
| [17.1](https://docs.nvidia.com/vgpu/17.0/index.html) | 550.54.16 | 551.60 | 550.54.15 | 551.78 | March 2024 |
| [17.0](https://docs.nvidia.com/vgpu/17.0/index.html) | 550.54.10 | 551.60 | 550.54.14 | 551.61 | February 2024 |

[Branch status](https://docs.nvidia.com/vgpu/news/vgpu-software-lifecycle-policy/):Long-Term Support Branch supported until July 2026

| vGPU Software | Linux vGPU Manager | Windows vGPU Manager | Linux Driver | Windows Driver | Release Date |
| --- | --- | --- | --- | --- | --- |
| [16.11](https://docs.nvidia.com/vgpu/16.0/index.html) | 535.261.04 | 539.45 | 535.261.03 | 539.41 | July 2025 |
| [16.10](https://docs.nvidia.com/vgpu/16.0/index.html) | 535.247.02 | 539.28 | 535.247.01 | 539.28 | April 2025 |
| [16.9](https://docs.nvidia.com/vgpu/16.0/index.html) | 535.230.02 | 539.14 | 535.230.02 | 539.19 | January 2025 |
| [16.8](https://docs.nvidia.com/vgpu/16.0/index.html) | 535.216.01 | 538.95 | 535.216.01 | 538.95 | October 2024 |
| [16.7](https://docs.nvidia.com/vgpu/16.0/index.html) | 535.183.04 | 538.67 | 535.183.06 | 538.78 | July 2024 |
| 16.6 | 535.183.04 | 538.67 | 535.183.01 | 538.67 | June 2024 |
| [16.5](https://docs.nvidia.com/vgpu/16.0/index.html) | 535.161.05 | 538.33 | 535.161.08 | 538.46 | March 2024 |
| [16.4](https://docs.nvidia.com/vgpu/16.0/index.html) | 535.161.05 | 538.33 | 535.161.07 | 538.33 | February 2024 |
| [16.3](https://docs.nvidia.com/vgpu/16.0/index.html) | 535.154.02 | 538.15 | 535.154.05 | 538.15 | January 2024 |
| [16.2](https://docs.nvidia.com/vgpu/16.0/index.html) | 535.129.03 | 537.70 | 535.129.03 | 537.70 | October 2023 |
| [16.1](https://docs.nvidia.com/vgpu/16.0/index.html) | 535.104.06 | 537.13 | 535.104.05 | 537.13 | August 2023 |
| [16.0](https://docs.nvidia.com/vgpu/16.0/index.html) | 535.54.06 | 536.22 | 535.54.03 | 536.25 | July 2023 |

[Branch status](https://docs.nvidia.com/vgpu/news/vgpu-software-lifecycle-policy/): Production Branch EOL from December 2023

| vGPU Software | Linux vGPU Manager | Windows vGPU Manager | Linux Driver | Windows Driver | Release Date |
| --- | --- | --- | --- | --- | --- |
| [15.4](https://docs.nvidia.com/vgpu/15.0/index.html) | 525.147.01 | 529.19 | 525.147.05 | 529.19 | October 2023 |
| [15.3](https://docs.nvidia.com/vgpu/15.0/index.html) | 525.125.03 | 529.06 | 525.125.06 | 529.11 | June 2023 |
| [15.2](https://docs.nvidia.com/vgpu/15.0/index.html) | 525.105.14 | 528.89 | 525.105.17 | 528.89 | March 2023 |
| [15.1](https://docs.nvidia.com/vgpu/15.0/index.html) | 525.85.07 | 528.24 | 525.85.05 | 528.24 | January 2023 |
| [15.0](https://docs.nvidia.com/vgpu/15.0/index.html) | 525.60.12 | 527.41 | 525.60.13 | 527.41 | December 2022 |

[Branch status](https://docs.nvidia.com/vgpu/news/vgpu-software-lifecycle-policy/): Production Branch EOL from February 2023

| vGPU Software | vGPU Manager | Linux Driver | Windows Driver | Release Date |
| --- | --- | --- | --- | --- |
| [14.4](https://docs.nvidia.com/vgpu/14.0/index.html) | 510.108.03 | 510.108.03 | 514.08 | December 2022 |
| [14.3](https://docs.nvidia.com/vgpu/14.0/index.html) | 510.108.03 | 510.108.03 | 513.91 | November 2022 |
| [14.2](https://docs.nvidia.com/vgpu/14.0/index.html) | 510.85.03 | 510.85.02 | 513.46 | August 2022 |
| [14.1](https://docs.nvidia.com/vgpu/14.0/index.html) | 510.73.06 | 510.73.08 | 512.78 | May 2022 |
| [14.0](https://docs.nvidia.com/vgpu/14.0/index.html) | 510.47.03 | 510.47.03 | 511.65 | February 2022 |

[Branch status](https://docs.nvidia.com/vgpu/news/vgpu-software-lifecycle-policy/):Long-Term Support Branch EOL since August 2024

| vGPU Software | vGPU Manager | Linux Driver | Windows Driver | Release Date |
| --- | --- | --- | --- | --- |
| [13.12](https://docs.nvidia.com/vgpu/13.0/index.html) | 470.256.02 | 470.256.02 | 475.14 | July 2024 |
| [13.11](https://docs.nvidia.com/vgpu/13.0/index.html) | 470.256.02 | 470.256.02 | 475.06 | June 2024 |
| [13.10](https://docs.nvidia.com/vgpu/13.0/index.html) | 470.239.01 | 470.239.06 | 474.82 | February 2024 |
| [13.9](https://docs.nvidia.com/vgpu/13.0/index.html) | 470.223.02 | 470.223.02 | 474.64 | October 2023 |
| [13.8](https://docs.nvidia.com/vgpu/13.0/index.html) | 470.199.03 | 470.199.02 | 474.44 | June 2023 |
| [13.7](https://docs.nvidia.com/vgpu/13.0/index.html) | 470.182.02 | 470.182.03 | 474.30 | March 2023 |
| [13.6](https://docs.nvidia.com/vgpu/13.0/index.html) | 470.161.02 | 470.161.03 | 474.14 | December 2022 |
| [13.5](https://docs.nvidia.com/vgpu/13.0/index.html) | 470.161.02 | 470.161.03 | 474.04 | November 2022 |
| [13.4](https://docs.nvidia.com/vgpu/13.0/index.html) | 470.141.05 | 470.141.03 | 473.81 | August 2022 |
| [13.3](https://docs.nvidia.com/vgpu/13.0/index.html) | 470.129.04 | 470.129.06 | 473.47 | May 2022 |
| [13.2](https://docs.nvidia.com/vgpu/13.0/index.html) | 470.103.02 | 470.103.01 | 472.98 | February 2022 |
| [13.1](https://docs.nvidia.com/vgpu/13.0/index.html) | 470.82 | 470.82.01 | 472.39 | November 2021 |
| [13.0](https://docs.nvidia.com/vgpu/13.0/index.html) | 470.63 | 470.63.01 | 471.68 | August 2021 |

[Branch status](https://docs.nvidia.com/vgpu/news/vgpu-software-lifecycle-policy/): Production Branch EOL from January 2022

| vGPU Software | vGPU Manager | Linux Driver | Windows Driver | Release Date |
| --- | --- | --- | --- | --- |
| [12.4](https://docs.nvidia.com/vgpu/12.0/index.html) | 460.107 | 460.106.00 | 463.15 | October 2021 |
| [12.3](https://docs.nvidia.com/vgpu/12.0/index.html) | 460.91.03 | 460.91.03 | 462.96 | July 2021 |
| [12.2](https://docs.nvidia.com/vgpu/12.0/index.html) | 460.73.02 | 460.73.01 | 462.31 | April 2021 |
| [12.1](https://docs.nvidia.com/vgpu/12.0/index.html) | 460.32.04 | 460.32.03 | 461.33 | February 2021 |
| [12.0](https://docs.nvidia.com/vgpu/12.0/index.html) | 460.32.04 | 460.32.03 | 461.09 | January 2021 |

[Branch status](https://docs.nvidia.com/vgpu/news/vgpu-software-lifecycle-policy/): Long-Term Support Branch EOL from July 2023

| vGPU Software | vGPU Manager | Linux Driver | Windows Driver | Release Date |
| --- | --- | --- | --- | --- |
| [11.13](https://docs.nvidia.com/vgpu/11.0/index.html) | 450.248.03 | 450.248.02 | 454.23 | June 2023 |
| [11.12](https://docs.nvidia.com/vgpu/11.0/index.html) | 450.236.03 | 450.236.01 | 454.14 | March 2023 |
| [11.11](https://docs.nvidia.com/vgpu/11.0/index.html) | 450.216.04 | 450.216.04 | 454.02 | December 2022 |
| [11.10](https://docs.nvidia.com/vgpu/11.0/index.html) | 450.216.04 | 450.216.04 | 453.94 | November 2022 |
| [11.9](https://docs.nvidia.com/vgpu/11.0/index.html) | 450.203 | 450.203.02 | 453.64 | August 2022 |
| [11.8](https://docs.nvidia.com/vgpu/11.0/index.html) | 450.191 | 450.191.01 | 453.51 | May 2022 |
| [11.7](https://docs.nvidia.com/vgpu/11.0/index.html) | 450.172 | 450.172.01 | 453.37 | January 2022 |
| [11.6](https://docs.nvidia.com/vgpu/11.0/index.html) | 450.156 | 450.156.00 | 453.23 | October 2021 |
| [11.5](https://docs.nvidia.com/vgpu/11.0/index.html) | 450.142 | 450.142.00 | 453.10 | July 2021 |
| [11.4](https://docs.nvidia.com/vgpu/11.0/index.html) | 450.124 | 450.119.03 | 452.96 | April 2021 |
| [11.3](https://docs.nvidia.com/vgpu/11.0/index.html) | 450.102 | 450.102.04 | 452.77 | January 2021 |
| [11.2](https://docs.nvidia.com/vgpu/11.0/index.html) | 450.89 | 450.89 | 452.57 | November 2020 |
| [11.1](https://docs.nvidia.com/vgpu/11.0/index.html) | 450.80 | 450.80.02 | 452.39 | September 2020 |
| [11.0](https://docs.nvidia.com/vgpu/11.0/index.html) | 450.55 | 450.51.05 | 451.48 | July 2020 |

[Branch status](https://docs.nvidia.com/vgpu/news/vgpu-software-lifecycle-policy/): Production Branch EOL from December 2020

| vGPU Software | vGPU Manager | Linux Driver | Windows Driver | Release Date |
| --- | --- | --- | --- | --- |
| [10.4](https://docs.nvidia.com/vgpu/10.0/index.html) | 440.121 | 440.118.02 | 443.66 | September 2020 |
| [10.3](https://docs.nvidia.com/vgpu/10.0/index.html) | 440.107 | 440.107 | 443.46 | July 2020 |
| [10.2](https://docs.nvidia.com/vgpu/10.0/index.html) | 440.87 | 440.87 | 443.05 | May 2020 |
| [10.1](https://docs.nvidia.com/vgpu/10.0/index.html) | 440.53 | 440.56 | 442.06 | February 2020 |
| [10.0](https://docs.nvidia.com/vgpu/10.0/index.html) | 440.43 | 440.43 | 441.66 | December 2019 |

[Branch status](https://docs.nvidia.com/vgpu/news/vgpu-software-lifecycle-policy/): Production Branch EOL from June 2020

| vGPU Software | vGPU Manager | Linux Driver | Windows Driver | Release Date |
| --- | --- | --- | --- | --- |
| [9.4](https://docs.nvidia.com/vgpu/9.0/index.html) | 430.99 | 430.99 | 432.44 | June 2020 |
| [9.3](https://docs.nvidia.com/vgpu/9.0/index.html) | 430.83 | 430.83 | 432.33 | March 2020 |
| [9.2](https://docs.nvidia.com/vgpu/9.0/index.html) | 430.67 | 430.63 | 432.08 | November 2019 |
| [9.1](https://docs.nvidia.com/vgpu/9.0/index.html) | 430.46 | 430.46 | 431.79 | August 2019 |
| [9.0](https://docs.nvidia.com/vgpu/9.0/index.html) | 430.27 | 430.30 | 431.02 | June 2019 |

[Branch status](https://docs.nvidia.com/vgpu/news/vgpu-software-lifecycle-policy/): Long-Term Support Branch EOL from April 2022

| vGPU Software | vGPU Manager | Linux Driver | Windows Driver | Release Date |
| --- | --- | --- | --- | --- |
| [8.10](https://docs.nvidia.com/vgpu/8.0/index.html) | 418.240 | 418.240 | 427.71 | January 2022 |
| [8.9](https://docs.nvidia.com/vgpu/8.0/index.html) | 418.226.00 | 418.226.00 | 427.60 | October 2021 |
| [8.8](https://docs.nvidia.com/vgpu/8.0/index.html) | 418.213 | 418.211.00 | 427.48 | July 2021 |
| [8.7](https://docs.nvidia.com/vgpu/8.0/index.html) | 418.196 | 418.197.02 | 427.33 | April 2021 |
| [8.6](https://docs.nvidia.com/vgpu/8.0/index.html) | 418.181 | 418.181.07 | 427.11 | January 2021 |
| [8.5](https://docs.nvidia.com/vgpu/8.0/index.html) | 418.165.01 | 418.165.01 | 426.94 | September 2020 |
| [8.4](https://docs.nvidia.com/vgpu/8.0/index.html) | 418.149 | 418.149 | 426.72 | June 2020 |
| [8.3](https://docs.nvidia.com/vgpu/8.0/index.html) | 418.130 | 418.130 | 426.52 | February 2020 |
| [8.2](https://docs.nvidia.com/vgpu/8.0/index.html) | 418.109 | 418.109 | 426.26 | October 2019 |
| [8.1](https://docs.nvidia.com/vgpu/8.0/index.html) | 418.92 | 418.92 | 426.04 | August 2019 |
| [8.0](https://docs.nvidia.com/vgpu/8.0/index.html) | 418.66 | 418.70 | 425.31 | April 2019 |

[Branch status](https://docs.nvidia.com/vgpu/news/vgpu-software-lifecycle-policy/): Production Branch EOL from October 2019

| vGPU Software | vGPU Manager | Linux Driver | Windows Driver | Release Date |
| --- | --- | --- | --- | --- |
| [7.5](https://docs.nvidia.com/vgpu/7.0/index.html) | 410.137 | 410.141 | 412.47 | October 2019 |
| [7.4](https://docs.nvidia.com/vgpu/7.0/index.html)[1](https://docs.nvidia.com/vgpu/index.html.md#release-7-4-withdrawal-note) | 410.137 | 410.137 | 412.45 | October 2019 |
| [7.3](https://docs.nvidia.com/vgpu/7.0/index.html) | 410.122 | 410.122 | 412.38 | July 2019 |
| [7.2](https://docs.nvidia.com/vgpu/7.0/index.html) | 410.107 | 410.107 | 412.31 | March 2019 |
| [7.1](https://docs.nvidia.com/vgpu/7.0/index.html) | 410.91 | 410.92 | 412.16 | December 2018 |
| [7.0](https://docs.nvidia.com/vgpu/7.0/index.html) | 410.68 | 410.71 | 411.81 | October 2018 |

1.   NVIDIA vGPU software release 7.4 was withdrawn after NVIDIA identified an issue with the NVIDIA virtual GPU software 7.4 graphics drivers for Windows and Linux. This issue impacts customers using GPU pass through with some hardware configurations and causes the graphics driver to fail to load with error code 43. NVIDIA has released a fix for this issue in NVIDIA virtual GPU software 7.5.

[Branch status](https://docs.nvidia.com/vgpu/news/vgpu-software-lifecycle-policy/): EOL from March 2019

| vGPU Software | vGPU Manager | Linux Driver | Windows Driver | Release Date |
| --- | --- | --- | --- | --- |
| [6.4](https://docs.nvidia.com/vgpu/6.0/index.html) | 390.113 | 390.115 | 392.37 | February 2019 |
| [6.3](https://docs.nvidia.com/vgpu/6.0/index.html) | 390.94 | 390.96 | 392.05 | October 2018 |
| [6.2](https://docs.nvidia.com/vgpu/6.0/index.html) | 390.72 | 390.75 | 391.81 | July 2018 |
| [6.1](https://docs.nvidia.com/vgpu/6.0/index.html) | 390.57 | 390.57 | 391.58 | May 2018 |
| [6.0](https://docs.nvidia.com/vgpu/6.0/index.html) | 390.42 | 390.42 | 391.03 | March 2018 |

[Branch status](https://docs.nvidia.com/vgpu/news/vgpu-software-lifecycle-policy/): EOL from August 2018

| vGPU Software | vGPU Manager | Linux Driver | Windows Driver | Release Date |
| --- | --- | --- | --- | --- |
| [5.4](https://docs.nvidia.com/vgpu/5.0/index.html) | 384.155 | 384.155 | 386.57 | August 2018 |
| [5.3](https://docs.nvidia.com/vgpu/5.0/index.html) | 384.137 | 384.137 | 386.37 | April 2018 |
| [5.2](https://docs.nvidia.com/vgpu/5.0/index.html) | 384.111 | 384.111 | 386.09 | January 2018 |
| [5.1](https://docs.nvidia.com/vgpu/5.0/index.html) | 384.99 | 384.99 | 385.90 | November 2017 |
| [5.0](https://docs.nvidia.com/vgpu/5.0/index.html) | 384.73 | 384.73 | 385.41 | August 2017 |

[Branch status](https://docs.nvidia.com/vgpu/news/vgpu-software-lifecycle-policy/): EOL from January 2020

| GRID Software | vGPU Manager | Linux Driver | Windows Driver | Release Date |
| --- | --- | --- | --- | --- |
| [4.10](https://docs.nvidia.com/vgpu/4.10/index.html) | 367.134 | 367.134 | 370.41 | January 2020 |
| [4.9](https://docs.nvidia.com/vgpu/4.9/index.html) | 367.132 | 367.133 | 370.39 | September 2019 |
| [4.8](https://docs.nvidia.com/vgpu/4.8/index.html) | 367.130 | 367.130 | 370.35 | March 2019 |
| [4.7](https://docs.nvidia.com/vgpu/4.7/index.html) | 367.128 | 367.128 | 370.28 | July 2018 |
| [4.6](https://docs.nvidia.com/vgpu/4.6/index.html) | 367.124 | 367.124 | 370.21 | January 2018 |
| [4.5](https://docs.nvidia.com/vgpu/4.5/index.html) | 367.123 | 367.123 | 370.17 | December 2017 |
| [4.4](https://docs.nvidia.com/vgpu/4.4/index.html) | 367.122 | 367.122 | 370.16 | September 2017 |
| [4.3](https://docs.nvidia.com/vgpu/4.3/index.html) | 367.106 | 367.106 | 370.12 | June 2017 |
| [4.2](https://docs.nvidia.com/vgpu/4.2/index.html) | 367.92 | 367.92 | 369.95 | March 2017 |
| [4.1](https://docs.nvidia.com/vgpu/4.1/index.html) | 367.64 | 367.64 | 369.71 | November 2016 |
| [4.0](https://docs.nvidia.com/vgpu/4.0/index.html) | 367.43 | 367.43 | 369.17 | August 2016 |

[Branch status](https://docs.nvidia.com/vgpu/news/vgpu-software-lifecycle-policy/): EOL from April 2019

| GRID Software | vGPU Manager | Linux Driver | Windows Driver | Release Date |
| --- | --- | --- | --- | --- |
| [3.4](https://docs.nvidia.com/vgpu/3.4/index.html) | 361.45.48 | 361.45.48 | 363.36 | March 2017 |
| [3.3](https://docs.nvidia.com/vgpu/3.3/index.html) | 361.45.44 | 361.45.44 | 363.24 | December 2016 |
| [3.2](https://docs.nvidia.com/vgpu/3.2/index.html) | 361.45.26 | 361.45.26 | 363.07 | September 2016 |
| [3.1](https://docs.nvidia.com/vgpu/3.1/index.html) | 361.45.09 | 361.45.09 | 362.56 | May 2016 |
| [3.0](https://docs.nvidia.com/vgpu/3.0/index.html) | 361.40 | 361.45 | 362.13 | April 2016 |

[Branch status](https://docs.nvidia.com/vgpu/news/vgpu-software-lifecycle-policy/): EOL from August 2018

| GRID Software | vGPU Manager | Linux Driver | Windows Driver | Release Date |
| --- | --- | --- | --- | --- |
| [2.5](https://docs.nvidia.com/vgpu/2.5/index.html) | 352.103 | 352.103 | 356.60 | March 2017 |
| [2.4](https://docs.nvidia.com/vgpu/2.4/index.html) | 353.01 | 353.01 | 356.53 | August 2016 |
| [2.3](https://docs.nvidia.com/vgpu/2.3/index.html) | 352.97 | 352.97 | 354.97 | May 2016 |
| [2.2](https://docs.nvidia.com/vgpu/2.2/index.html) | 352.83 | 352.83 | 354.80 | February 2016 |

Identify the right GPU, virtualization product, and vGPU size for your needs.

[Browse](https://docs.nvidia.com/vgpu/sizing/index.html)

Quickly configure NVIDIA vGPU software.

[Browse](https://docs.nvidia.com/vgpu/17.0/grid-software-quick-start-guide/index.html.md)

Deploy NVIDIA vGPU on the supported hypervisor of your choice.

[Browse](https://docs.nvidia.com/vgpu/deployment/index.html)

Deploy NVIDIA vGPU on the supported cloud provider of your choice.

[Browse](https://docs.nvidia.com/vgpu/qvws/latest/index.html.md)

Set up and use the NVIDIA License System service for vGPU.

[Browse](https://docs.nvidia.com/license-system/latest/)

Manage NVIDIA GPUs from VMware vCenter.

[Browse](https://docs.nvidia.com/vgpu/vmware-vcenter-gpu-manager/index.html)

Monitor the performance of NVIDIA GPUs and virtual GPUs from VMware Aria Operations (formerly vROps).

[Browse](https://docs.nvidia.com/vgpu/vrops/index.html)

This document offers a comprehensive overview of virtual GPU (vGPU) features across major hypervisors, empowering customers to compare and understand vGPU capabilities for optimized deployment and performance.

[Browse](https://docs.nvidia.com/vgpu/knowledge-base/latest/index.html.md)

This toolkit includes deployment and sizing guides to build a Retrieval-Augmented Generation (RAG) application with NVIDIA RTX Virtual Workstation.

[Browse](https://docs.nvidia.com/vgpu/toolkits/rag-application/latest/index.html.md)

This toolkit includes deployment and sizing guides on how to transform PDF files to AI-generated podcasts with NVIDIA RTX Virtual Workstation by using NVIDIA NIMs and NVIDIA Blueprints.

[Browse](https://docs.nvidia.com/vgpu/toolkits/pdf-to-podcasts/latest/index.html.md)

This toolkit includes deployment and sizing guides for fine-tuning and customizing LLMs with NVIDIA RTX Virtual Workstation.

[Browse](https://docs.nvidia.com/vgpu/toolkits/fine-tunning-llms/latest/index.html.md)

This toolkit includes a deployment guide to build an Agentic Retrieval-Augmented Generation (RAG) with NVIDIA RTX Virtual Workstation.

[Browse](https://docs.nvidia.com/vgpu/toolkits/agentic-rag/latest/index.html)

Links/Buttons:
- [1](https://docs.nvidia.com/vgpu/index.html.md#release-7-4-withdrawal-note)
- [vGPU Branch Type](https://docs.nvidia.com/grid/news/vgpu-software-lifecycle-policy/)
- [NVIDIA vGPU 19](https://docs.nvidia.com/vgpu/19.0/index.html)
- [Long-Term Support](https://docs.nvidia.com/vgpu/news/vgpu-software-lifecycle-policy/#ltsb-releases)
- [NVIDIA vGPU 18](https://docs.nvidia.com/vgpu/18.0/index.html.md)
- [Production](https://nam11.safelinks.protection.outlook.com/?url=https%3A%2F%2Fdocs.nvidia.com%2Fvgpu%2Fnews%2Fvgpu-software-lifecycle-policy%2F%23nfb-releases&data=05%7C02%7Crkashireddy%40nvidia.com%7C0bdf3c8848104340ea2b08dd5b2f3613%7C43083d15727340c1b7db39efd9ccc17a%7C0%7C0%7C638766980564840794%7CUnknown%7CTWFpbGZsb3d8eyJFbXB0eU1hcGkiOnRydWUsIlYiOiIwLjAuMDAwMCIsIlAiOiJXaW4zMiIsIkFOIjoiTWFpbCIsIldUIjoyfQ%3D%3D%7C0%7C%7C%7C&sdata=7NXdCSOkkNVIhSujWrhPHW2Lv5vO9xbCKEhNyFQU2OI%3D&reserved=0)
- [NVIDIA vGPU 16](https://docs.nvidia.com/vgpu/16.0/index.html)
- [NVIDIA vGPU 17](https://docs.nvidia.com/grid/17.0/index.html)
- [NVIDIA vGPU 15](https://docs.nvidia.com/grid/15.0/index.html)
- [NVIDIA vGPU 14](https://docs.nvidia.com/grid/14.0/index.html)
- [NVIDIA vGPU 13](https://docs.nvidia.com/grid/13.0/index.html)
- [NVIDIA vGPU 12](https://docs.nvidia.com/grid/12.0/index.html)
- [NVIDIA vGPU 11](https://docs.nvidia.com/grid/11.0/index.html)
- [NVIDIA vGPU 10](https://docs.nvidia.com/grid/10.0/index.html)
- [NVIDIA vGPU 9](https://docs.nvidia.com/grid/9.0/index.html)
- [NVIDIA vGPU 8](https://docs.nvidia.com/grid/8.0/index.html)
- [NVIDIA vGPU 7](https://docs.nvidia.com/grid/7.0/index.html)
- [NVIDIA vGPU 6](https://docs.nvidia.com/grid/6.0/index.html)
- [NVIDIA vGPU 5](https://docs.nvidia.com/grid/5.0/index.html)
- [NVIDIA GRID 4](https://docs.nvidia.com/grid/4.10/index.html)
- [NVIDIA GRID 3](https://docs.nvidia.com/grid/3.4/index.html)
- [NVIDIA GRID 2](https://docs.nvidia.com/grid/2.5/index.html)
- [NVIDIA Virtual GPU Software Lifecycle Policy](https://docs.nvidia.com/grid/news/vgpu-software-lifecycle-policy/#abstract)
- [Branch status](https://docs.nvidia.com/vgpu/news/vgpu-software-lifecycle-policy/)
- [17.6](https://docs.nvidia.com/vgpu/17.0/index.html)
- [15.4](https://docs.nvidia.com/vgpu/15.0/index.html)
- [14.4](https://docs.nvidia.com/vgpu/14.0/index.html)
- [13.12](https://docs.nvidia.com/vgpu/13.0/index.html)
- [12.4](https://docs.nvidia.com/vgpu/12.0/index.html)
- [11.13](https://docs.nvidia.com/vgpu/11.0/index.html)
- [10.4](https://docs.nvidia.com/vgpu/10.0/index.html)
- [9.4](https://docs.nvidia.com/vgpu/9.0/index.html)
- [8.10](https://docs.nvidia.com/vgpu/8.0/index.html)
- [7.5](https://docs.nvidia.com/vgpu/7.0/index.html)
- [6.4](https://docs.nvidia.com/vgpu/6.0/index.html)
- [5.4](https://docs.nvidia.com/vgpu/5.0/index.html)
- [4.10](https://docs.nvidia.com/vgpu/4.10/index.html)
- [4.9](https://docs.nvidia.com/vgpu/4.9/index.html)
- [4.8](https://docs.nvidia.com/vgpu/4.8/index.html)
- [4.7](https://docs.nvidia.com/vgpu/4.7/index.html)
- [4.6](https://docs.nvidia.com/vgpu/4.6/index.html)
- [4.5](https://docs.nvidia.com/vgpu/4.5/index.html)
- [4.4](https://docs.nvidia.com/vgpu/4.4/index.html)
- [4.3](https://docs.nvidia.com/vgpu/4.3/index.html)
- [4.2](https://docs.nvidia.com/vgpu/4.2/index.html)
- [4.1](https://docs.nvidia.com/vgpu/4.1/index.html)
- [4.0](https://docs.nvidia.com/vgpu/4.0/index.html)
- [3.4](https://docs.nvidia.com/vgpu/3.4/index.html)
- [3.3](https://docs.nvidia.com/vgpu/3.3/index.html)
- [3.2](https://docs.nvidia.com/vgpu/3.2/index.html)
- [3.1](https://docs.nvidia.com/vgpu/3.1/index.html)
- [3.0](https://docs.nvidia.com/vgpu/3.0/index.html)
- [2.5](https://docs.nvidia.com/vgpu/2.5/index.html)
- [2.4](https://docs.nvidia.com/vgpu/2.4/index.html)
- [2.3](https://docs.nvidia.com/vgpu/2.3/index.html)
- [2.2](https://docs.nvidia.com/vgpu/2.2/index.html)
- [Selection Guides: Positioning and Sizing](https://docs.nvidia.com/vgpu/sizing/index.html)
- [Quick Start Guide](https://docs.nvidia.com/vgpu/17.0/grid-software-quick-start-guide/index.html.md)
- [Deployment Guides: On-Prem (hypervisors)](https://docs.nvidia.com/vgpu/deployment/index.html)
- [Deployment Guides: Cloud](https://docs.nvidia.com/vgpu/qvws/latest/index.html.md)
- [Licensing Guide (NLS)](https://docs.nvidia.com/license-system/latest/)
- [NVIDIA GPU Manager Plug-In for vCenter](https://docs.nvidia.com/vgpu/vmware-vcenter-gpu-manager/index.html)
- [vGPU Management Pack for VMware Aria Operations](https://docs.nvidia.com/vgpu/vrops/index.html)
- [Comprehensive Knowledge Base on vGPU Features Across Hypervisors](https://docs.nvidia.com/vgpu/knowledge-base/latest/index.html.md)
- [AI vWS Toolkit - Building a RAG Application with RTX vWS](https://docs.nvidia.com/vgpu/toolkits/rag-application/latest/index.html.md)
- [AI vWS Toolkit - Converting PDFs to AI-Generated Podcasts](https://docs.nvidia.com/vgpu/toolkits/pdf-to-podcasts/latest/index.html.md)
- [AI vWS Toolkit - Fine-Tuning and Customizing LLMs](https://docs.nvidia.com/vgpu/toolkits/fine-tunning-llms/latest/index.html.md)
- [AI vWS Toolkit - Building an Agentic RAG](https://docs.nvidia.com/vgpu/toolkits/agentic-rag/latest/index.html)
- [GPUs Supported by NVIDIA vGPU](https://docs.nvidia.com/vgpu/gpus-supported-by-vgpu.html.md)
- [GPU Software Lifecycle for NVIDIA vGPU](https://docs.nvidia.com/vgpu/news/vgpu-software-lifecycle-on-supported-gpus/index.html.md)
- [News and Updates](https://docs.nvidia.com/grid/news/index.html.md)
- [Product Download and Support Portal](http://nvid.nvidia.com/dashboard.md/)
- [Free Evaluation License](http://www.nvidia.com/object/vgpu-evaluation.html)
- [vGPU FAQs](https://docs.nvidia.com/vgpu/faq/latest/index.html.md)
- [vGPU Troubleshooting Guide](https://docs.nvidia.com/vgpu/troubleshooting/latest/index.html.md)
- [YouTube Channel](https://www.youtube.com/playlist?list=PL5B692fm6--vfyGFgx9ZVrCG-lTpqENPZ)
- [vGPU Forums](https://forums.developer.nvidia.com/c/nvidia-virtual-gpu-forums/328)
- [Supported Cloud Services](https://docs.nvidia.com/grid/cloud-service-support.html.md)
- [NVIDIA RTX Virtual Workstation Cloud Documentation](https://docs.nvidia.com/grid/qvws/index.html.md)
- [NVIDIA AI Enterprise Documentation](https://docs.nvidia.com/ai-enterprise/index.html.md)
- [Legacy vGPU Software License Server Documentation](https://docs.nvidia.com/grid/ls/index.html)
