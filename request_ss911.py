import requests

url = "https://t1.ss911.cn/Rank/GetToolRank.ss"
params = {
    "toolid": "781",
    # "toolid": "1011",
    "h": "0",
    "g": "0",
    "n": "3",
    "p": "1",
    "u": "ghmJW19X9hLGabVsFcTN%2FTshF0t%2Fpecr7ifwpVk74yE%3D"
}

# TODO: 填入你的 Cookie
cookie = "JSESSIONID=F9257055C5772AB3E8712872FF04674F; Hm_lvt_8db5877631f6b3e1e50b3a82695c5484=1777547687,1777731807,1778506341,1778936394; HMACCOUNT=410244466E960FFE; UserId=126521216; UserName=14705896759; UserPwd=3115e599ad5a97c0; uservalues=ghmJW19X9hLGabVsFcTN%2FTshF0t%2Fpecr7ifwpVk74yE%3D; LastLogin=2026-05-16~21:00:05; yzmCode=wcvqGqJhW68Z8trn%2B184%2BBOWb59LRIeZ; Hm_lpvt_8db5877631f6b3e1e50b3a82695c5484=1778936405"

headers = {}
if cookie:
    headers["Cookie"] = cookie

response = requests.get(url, params=params, headers=headers)
print(f"Status: {response.status_code}")
print(f"Response: {response.text}")
