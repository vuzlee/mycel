"""Điểm vào của hệ thống, chia theo miền nghiệp vụ.

HTTP không gọi thẳng service. Nó gọi vào manager của miền tương ứng; bên trong
manager mới có endpoint và chuỗi nghiệp vụ:

  managers/report/      mọi thứ liên quan tới báo cáo
    controller.py       endpoint HTTP — nhận, validate, trả
    pipeline.py         chuỗi nghiệp vụ — gọi lần lượt các service

Thêm một miền mới = thêm một thư mục ở đây. Không đụng miền đang có.

Vì sao chia theo miền chứ không theo kỹ thuật: sửa một nghiệp vụ thì mở đúng
một thư mục, không phải nhảy giữa routes/, services/ và pipeline/.
"""
